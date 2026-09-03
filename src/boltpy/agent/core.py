"""Conversation state and the reusable Boltpy agent loop."""
from __future__ import annotations
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
import re
import time
from typing import Any
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionMode
from boltpy.agent.providers import Message, Provider, ProviderEvent, build_provider
from boltpy.agent.text import normalize_response_text
from boltpy.agent.todos import TaskState
from boltpy.agent.tools import ToolRegistry, ToolResult, default_registry, parse_arguments
from boltpy.config import Settings

OptionsHandler = Callable[[str, list[str], bool], Awaitable[str] | str]

@dataclass
class AgentRunStats:
    """Metrics for one stream_events invocation."""
    tool_iterations: int = 0
    tool_calls: int = 0
    repeated_failures: int = 0
    elapsed_seconds: float = 0.0


@dataclass
class AgentEvent:
    """Stream event consumed by the CLI/TUI adapters."""
    kind: str
    text: str = ""
    name: str = ""
    arguments: dict[str, Any] | None = None
    result: ToolResult | None = None
    status: str = ""

_VALIDATION_COMMANDS = re.compile(
    r"\b(pytest|unittest|tox|nox|nose|jest|vitest|mocha|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test|"
    r"npm\s+(?:run\s+)?test|yarn\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|make\s+(?:test|check)|"
    r"(?:ruff|flake8| pylint|mypy|pyright|eslint|tsc|shellcheck|compileall|cargo\s+check|go\s+vet))\b",
    re.IGNORECASE,
)
_BROAD_TASK_WORDS = re.compile(r"\b(all|entire|whole|full|project|every|everything|suite)\b", re.IGNORECASE)
_VALIDATION_INTENT = re.compile(
    r"\b(test(?:s|ing)?|build|pass(?:es|ing)?|validation|validat(?:e|ion)|verify|verif(?:y|ication)|"
    r"type[- ]?check|lint|compile|coverage)\b",
    re.IGNORECASE,
)

def _required_validation_scope(prompt: str) -> str:
    # Edits and explanations do not imply a validation obligation. Only an
    # explicit validation intent creates one; broad words select the required
    # breadth after that intent has been established.
    if not _VALIDATION_INTENT.search(prompt):
        return "unknown"
    return "project/full" if _BROAD_TASK_WORDS.search(prompt) else "targeted"

def _validation_scope(command: str) -> str:
    if not _VALIDATION_COMMANDS.search(command):
        return "unknown"
    lowered = command.casefold()
    explicit_target = bool(re.search(r"(?:pytest|unittest|jest|vitest|go\s+test|cargo\s+test)\s+[^;&|]*(?:/|\.py|\.go|\.rs)", lowered))
    return "targeted" if explicit_target else "project/full"

_PLAN_GUIDANCE = (
    "\n\nYou are in PLAN mode. Read-only tools run freely, but write, shell, SSH, and "
    "other capability-guarded actions are blocked. When the user asks for a change, "
    "propose a concise step-by-step plan and end your reply with the plan. The user can "
    "switch to ask/allow mode with /mode to let you execute it."
)

_TODO_GUIDANCE = (
    "\n\nTask tracking: For multi-step requests or work that will take more than one action, "
    "create a concise todo for each meaningful step with add_todo before starting. "
    "Use complete_todo immediately after a step is finished, update_todo if its scope "
    "changes, and list_todos when you need to review the current plan. Do not create "
    "todos for simple questions or one-step answers."
)

_CODING_GUIDANCE = (
    "\n\nCoding discipline: Inspect and search before editing. Make the smallest targeted change, "
    "preserve surrounding formatting, and validate edits with an appropriate available command. "
    "Treat tool results as the source of truth. Never claim success without a successful tool result."
)

_TOOL_DISCIPLINE_GUIDANCE = (
    "\n\nTool discipline: For remote work, use the ssh_execute tool with the literal host, user, "
    "and command; do not try to execute a shell alias on the remote host. "
    "For a Podman benchmark, use only the discovered aliases whose names end in digits; "
    "run plain sudo podman ps -a, stop only currently running names, start those same names, "
    "and verify with another plain listing. Never create, remove, replace, or rename containers. "
    "For run_shell, never substitute local shell for a remote request. The current working-directory path "
    "in the command field. The working directory is already configured separately. "
    "If a tool call fails, inspect its error, make at most one focused correction, and "
    "then report the blocker instead of trying unrelated alternatives. Never claim an "
    "operation succeeded unless a tool result confirms it."
)

class Agent:
    """History-aware agent supporting multiple tool calls and iterations."""
    def __init__(self, settings: Settings, provider: Provider | None = None,
                 registry: ToolRegistry | None = None, permissions: PermissionManager | None = None,
                 max_tool_iterations: int = 16, emit_lifecycle: bool = False,
                 vision_state: Callable[[], bool | None] | None = None) -> None:
        self.settings = settings
        self.provider = provider or build_provider(settings)
        self.messages: list[Message] = [{"role": "system", "content": settings.system_prompt}]
        self.registry = registry or default_registry(
            settings.workspace, self.provider, settings.vision_enabled, vision_state,
        )
        self.permissions = permissions or PermissionManager(mode=settings.permission_mode)
        self.options_handler: OptionsHandler | None = None
        self.max_tool_iterations = max_tool_iterations
        self.emit_lifecycle = emit_lifecycle
        self.task_state: TaskState | None = None
        self.run_stats = AgentRunStats()
        self.messages[0]["content"] = self._system_prompt()

    def _system_prompt(self) -> str:
        content = self.settings.system_prompt
        if _TODO_GUIDANCE not in content:
            content += _TODO_GUIDANCE
        if _CODING_GUIDANCE not in content:
            content += _CODING_GUIDANCE
        if _TOOL_DISCIPLINE_GUIDANCE not in content:
            content += _TOOL_DISCIPLINE_GUIDANCE
        if self.permissions.mode == PermissionMode.PLAN and _PLAN_GUIDANCE not in content:
            content += _PLAN_GUIDANCE
        return content

    async def stream_events(self, prompt: str) -> AsyncIterator[AgentEvent]:
        """Run model → tools → model until final text or the loop limit."""
        self.messages.append({"role": "user", "content": prompt})
        self.run_stats = AgentRunStats()
        run_started = time.perf_counter()
        required_scope = _required_validation_scope(prompt)
        requires_validation = required_scope != "unknown"
        self.task_state = TaskState(
            objective=prompt,
            success_criteria=(["Complete the requested objective", "Validate the result when applicable"] if requires_validation else []),
            required_validation_scope=required_scope,
        )
        if self.emit_lifecycle:
            yield AgentEvent(kind="lifecycle", status="planning", text="Planning task")
        iterations = 0
        failed_calls: set[tuple[str, str, str]] = set()
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
                    response_text = normalize_response_text("".join(text_parts))
                    self.messages.append({"role": "assistant", "content": response_text})
                    if self.task_state is not None:
                        self.task_state.current_step = ""
                        self._finalize_task_state()
                    if self.emit_lifecycle:
                        yield AgentEvent(kind="lifecycle", status="completed", text="Task completed")
                        if self.task_state is not None:
                            yield AgentEvent(kind="task_result", status=self.task_state.completion_status, text=self._task_summary())
                    return
                iterations += 1
                self.run_stats.tool_iterations = iterations
                self.run_stats.tool_calls += len(calls)
                if iterations > self.max_tool_iterations:
                    for blocked_event in self._blocked_events(f"Tool-call loop exceeded {self.max_tool_iterations} iterations"):
                        yield blocked_event
                    return
                assistant_call_message: Message = {"role": "assistant", "content": normalize_response_text("".join(text_parts)), "tool_calls": []}
                parsed_calls: list[tuple[ProviderEvent, dict[str, Any], str | None]] = []
                for call in calls:
                    try:
                        arguments = parse_arguments(call.arguments)
                        argument_error = None
                    except ValueError as error:
                        arguments = {}
                        argument_error = str(error)
                    parsed_calls.append((call, arguments, argument_error))
                    assistant_call_message["tool_calls"].append({"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}})
                    yield AgentEvent(kind="tool_call", name=call.name, arguments=arguments, status="requested")
                    if self.task_state is not None:
                        self.task_state.current_step = call.name
                    if self.emit_lifecycle:
                        yield AgentEvent(kind="lifecycle", name=call.name, arguments=arguments, status="executing")
                self.messages.append(assistant_call_message)
                for call, arguments, argument_error in parsed_calls:
                    if argument_error is not None:
                        result = ToolResult(ok=False, error=argument_error)
                        self.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": result.as_message()})
                        yield AgentEvent(kind="tool_result", name=call.name, result=result, status="failed")
                        if self.emit_lifecycle:
                            yield AgentEvent(kind="lifecycle", name=call.name, status="observing")
                        fingerprint = (call.name, call.arguments, result.error)
                        if fingerprint in failed_calls:
                            self.run_stats.repeated_failures += 1
                            for blocked_event in self._blocked_events(result.error):
                                yield blocked_event
                            return
                        failed_calls.add(fingerprint)
                        if self.emit_lifecycle:
                            yield AgentEvent(kind="lifecycle", name=call.name, status="replanning")
                        continue
                    try:
                        tool = self.registry.get(call.name)
                        tool.validate(arguments)
                    except Exception as error:
                        result = ToolResult(ok=False, error=str(error))
                        self.messages.append({"role": "tool", "tool_call_id": call.call_id, "content": result.as_message()})
                        yield AgentEvent(kind="tool_result", name=call.name, result=result, status="failed")
                        if self.emit_lifecycle:
                            yield AgentEvent(kind="lifecycle", name=call.name, status="observing")
                        fingerprint = (call.name, call.arguments, result.error)
                        if fingerprint in failed_calls:
                            self.run_stats.repeated_failures += 1
                            for blocked_event in self._blocked_events(result.error):
                                yield blocked_event
                            return
                        failed_calls.add(fingerprint)
                        if self.emit_lifecycle:
                            yield AgentEvent(kind="lifecycle", name=call.name, status="replanning")
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
                    if self.emit_lifecycle:
                        yield AgentEvent(kind="lifecycle", name=call.name, status="observing")
                    if self.task_state is not None:
                        if result.ok:
                            failed_calls.clear()
                            step = f"{call.name} completed"
                            if step not in self.task_state.completed_steps:
                                self.task_state.completed_steps.append(step)
                            if call.name in {"run_command", "run_shell"}:
                                command = str(arguments.get("command", ""))
                                scope = _validation_scope(command)
                                if scope != "unknown":
                                    if self.emit_lifecycle:
                                        yield AgentEvent(kind="lifecycle", name=call.name, status="validating")
                                    self.task_state.validation_attempted = True
                                    self.task_state.validation_command = command
                                    self.task_state.validation_scope = scope
                                    self.task_state.verified_scope = scope
                                    self.task_state.validation_status = "passed"
                        else:
                            fingerprint = (call.name, repr(sorted(arguments.items())), result.error)
                            if fingerprint in failed_calls:
                                self.run_stats.repeated_failures += 1
                                for blocked_event in self._blocked_events(result.error or f"{call.name} failed repeatedly"):
                                    yield blocked_event
                                return
                            failed_calls.add(fingerprint)
                            if self.emit_lifecycle:
                                yield AgentEvent(kind="lifecycle", name=call.name, status="replanning")
                            if call.name in {"run_command", "run_shell"}:
                                command = str(arguments.get("command", ""))
                                scope = _validation_scope(command)
                                if scope != "unknown":
                                    self.task_state.validation_attempted = True
                                    self.task_state.validation_command = command
                                    self.task_state.validation_scope = scope
                                    self.task_state.verified_scope = "unknown"
                                    self.task_state.validation_status = "failed"
        except Exception:
            self.messages.pop()
            raise
        finally:
            self.run_stats.elapsed_seconds = time.perf_counter() - run_started

    def _finalize_task_state(self) -> None:
        """Derive task verification from recorded evidence, not model wording."""
        state = self.task_state
        if state is None:
            return
        if state.validation_status == "failed":
            state.completion_status = "blocked"
            if not state.failure:
                state.failure = f"Validation failed: {state.validation_command}"
        elif state.required_validation_scope == "unknown":
            state.completion_status = "completed"
            if state.validation_status == "not_run":
                state.validation_status = "not_applicable"
        elif state.validation_status != "passed":
            state.completion_status = "not_verified"
        elif state.required_validation_scope == "project/full" and state.validation_scope != "project/full":
            state.completion_status = "partially_verified"
        else:
            state.completion_status = "verified"

    def _task_summary(self) -> str:
        state = self.task_state
        if state is None:
            return ""
        messages = {
            "completed": "Task completed; validation was not required.",
            "verified": f"Task verified: {state.validation_scope} validation passed.",
            "partially_verified": f"Task partially verified: {state.validation_scope} validation passed; broader validation was not run.",
            "not_verified": "Task not verified: no successful validation was recorded.",
            "blocked": f"Task blocked: {state.failure or 'validation failed'}.",
        }
        return messages.get(state.completion_status, "Task remains in progress.")

    def _blocked_events(self, message: str) -> list[AgentEvent]:
        """Record a blocker and expose it without inventing a success result."""
        if self.task_state is not None:
            self.task_state.failure = message
            self.task_state.current_step = ""
            self.task_state.validation_status = "blocked"
        return [
            *([AgentEvent(kind="lifecycle", status="blocked", text=message)] if self.emit_lifecycle else []),
            AgentEvent(kind="text", text=f"Blocked: {message}"),
        ]

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
        self.task_state = None

    def restore_task_state(self, value: dict[str, Any] | None) -> None:
        self.task_state = TaskState.from_dict(value) if isinstance(value, dict) else None

    def set_permission_mode(self, mode: PermissionMode) -> None:
        """Switch permission mode and refresh plan-mode guidance in the system prompt."""
        self.permissions.mode = mode
        self.settings.permission_mode = mode.value
        self.messages[0]["content"] = self._system_prompt()

    async def close(self) -> None:
        await self.provider.close()
