"""Conversation state and the reusable Boltpy agent loop."""
from __future__ import annotations
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionMode
from boltpy.agent.providers import Message, OpenAICompatibleProvider, ProviderEvent
from boltpy.agent.tools import ToolRegistry, ToolResult, default_registry, parse_arguments
from boltpy.config import Settings

OptionsHandler = Callable[[str, list[str], bool], Awaitable[str] | str]

@dataclass
class AgentEvent:
    """Stream event consumed by the CLI/TUI adapters."""
    kind: str
    text: str = ""
    name: str = ""
    arguments: dict[str, Any] | None = None
    result: ToolResult | None = None
    status: str = ""

_PLAN_GUIDANCE = (
    "\n\nYou are in PLAN mode. Read-only tools run freely, but write, shell, SSH, and "
    "other capability-guarded actions are blocked. When the user asks for a change, "
    "propose a concise step-by-step plan and end your reply with the plan. The user can "
    "switch to ask/allow mode with /mode to let you execute it."
)

class Agent:
    """History-aware agent supporting multiple tool calls and iterations."""
    def __init__(self, settings: Settings, provider: OpenAICompatibleProvider | None = None,
                 registry: ToolRegistry | None = None, permissions: PermissionManager | None = None,
                 max_tool_iterations: int = 8) -> None:
        self.settings = settings
        self.provider = provider or OpenAICompatibleProvider(settings)
        self.messages: list[Message] = [{"role": "system", "content": settings.system_prompt}]
        self.registry = registry or default_registry()
        self.permissions = permissions or PermissionManager(mode=settings.permission_mode)
        self.options_handler: OptionsHandler | None = None
        self.max_tool_iterations = max_tool_iterations
        self.messages[0]["content"] = self._system_prompt()

    def _system_prompt(self) -> str:
        content = self.settings.system_prompt
        if self.permissions.mode == PermissionMode.PLAN and _PLAN_GUIDANCE not in content:
            content += _PLAN_GUIDANCE
        return content

    async def stream_events(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """Run model → tools → model until final text or the loop limit."""
        self.messages.append({"role": "user", "content": prompt})
        iterations = 0
        try:
            while True:
                text_parts: list[str] = []
                calls: list[ProviderEvent] = []
                if hasattr(self.provider, "stream_response"):
                    async for event in self.provider.stream_response(self.messages, self.registry.schemas()):
                        if event.kind == "text":
                            text_parts.append(event.text)
                            yield AgentEvent(kind="text", text=event.text)
                        else:
                            calls.append(event)
                else:  # compatibility with Phase 1 providers
                    async for text in self.provider.stream(self.messages):
                        text_parts.append(text)
                        yield AgentEvent(kind="text", text=text)
                if not calls:
                    self.messages.append({"role": "assistant", "content": "".join(text_parts)})
                    return
                iterations += 1
                if iterations > self.max_tool_iterations:
                    raise RuntimeError(f"Tool-call loop exceeded {self.max_tool_iterations} iterations")
                assistant_call_message: Message = {"role": "assistant", "content": "".join(text_parts), "tool_calls": []}
                parsed_calls: list[tuple[ProviderEvent, dict[str, Any]]] = []
                for call in calls:
                    arguments = parse_arguments(call.arguments)
                    parsed_calls.append((call, arguments))
                    assistant_call_message["tool_calls"].append({"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}})
                    yield AgentEvent(kind="tool_call", name=call.name, arguments=arguments, status="requested")
                self.messages.append(assistant_call_message)
                for call, arguments in parsed_calls:
                    try:
                        tool = self.registry.get(call.name)
                        tool.validate(arguments)
                    except Exception as error:
                        result = ToolResult(ok=False, error=str(error))
                        self.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": result.as_message()})
                        yield AgentEvent(kind="tool_result", name=call.name, result=result, status="failed")
                        continue
                    if tool.name == "present_options":
                        title = str(arguments.get("title", "Choose an option"))
                        options = [str(option) for option in arguments.get("options", []) if str(option).strip()]
                        allow_custom = bool(arguments.get("allow_custom", True))
                        if self.options_handler is not None:
                            selection = await self._call_options_handler(title, options, allow_custom)
                        else:
                            selection = options[0] if options else "(no options)"
                        result = ToolResult(ok=True, output=selection)
                        self.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": result.as_message()})
                        yield AgentEvent(kind="tool_result", name=call.name, result=result, status="completed")
                        continue
                    request = tool.permission_request(arguments)
                    decision = PermissionDecision.ALLOW_ONCE
                    if request is not None:
                        yield AgentEvent(kind="permission", name=call.name, arguments=arguments, status="waiting")
                        decision = await self.permissions.authorize(request)
                        yield AgentEvent(kind="permission", name=call.name, arguments=arguments, status=decision.value)
                    if decision == PermissionDecision.DENY:
                        result = ToolResult(ok=False, error="Permission denied")
                    else:
                        result = await self.registry.execute(call.name, arguments)
                    self.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": result.as_message()})
                    yield AgentEvent(kind="tool_result", name=call.name, result=result, status="completed" if result.ok else "failed")
        except Exception:
            self.messages.pop()
            raise

    async def _call_options_handler(self, title: str, options: list[str], allow_custom: bool) -> str:
        result = self.options_handler(title, options, allow_custom) if self.options_handler is not None else None
        if hasattr(result, "__await__"):
            result = await result
        return str(result)

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Compatibility text-only stream; tool events are still executed."""
        async for event in self.stream_events(prompt):
            if event.kind == "text": yield event.text

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self._system_prompt()}]

    def set_permission_mode(self, mode: PermissionMode) -> None:
        """Switch permission mode and refresh plan-mode guidance in the system prompt."""
        self.permissions.mode = mode
        self.settings.permission_mode = mode.value
        self.messages[0]["content"] = self._system_prompt()

    async def close(self) -> None:
        await self.provider.close()
