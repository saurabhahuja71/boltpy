"""OpenAI-compatible streaming provider."""
from __future__ import annotations
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any
from openai import AsyncOpenAI
from boltpy.config import Settings, require_api_key
Message = dict[str, Any]

@dataclass
class ProviderEvent:
    """One streamed assistant text fragment or completed tool call."""
    kind: str
    text: str = ""
    call_id: str = ""
    name: str = ""
    arguments: str = ""

class OpenAICompatibleProvider:
    """Thin provider wrapper shared by headless and TUI modes."""
    def __init__(self, settings: Settings) -> None:
        kwargs: dict[str, Any] = {"api_key": require_api_key(settings)}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = settings.model
        self.temperature = settings.temperature

    async def stream_response(self, messages: Sequence[Message], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[ProviderEvent]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": list(messages), "temperature": self.temperature, "stream": True}
        if tools:
            kwargs["tools"] = tools
        response = await self.client.chat.completions.create(**kwargs)
        calls: dict[int, dict[str, str]] = {}
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield ProviderEvent(kind="text", text=delta.content)
            for call in delta.tool_calls or []:
                item = calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                if call.id:
                    item["id"] = call.id
                if call.function and call.function.name:
                    item["name"] = call.function.name
                if call.function and call.function.arguments:
                    item["arguments"] += call.function.arguments
        for item in calls.values():
            yield ProviderEvent(kind="tool_call", call_id=item["id"], name=item["name"], arguments=item["arguments"])

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Compatibility text-only stream used by older integrations."""
        async for event in self.stream_response(messages):
            if event.kind == "text":
                yield event.text

    async def close(self) -> None:
        await self.client.close()
