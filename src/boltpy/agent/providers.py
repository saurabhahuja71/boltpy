"""OpenAI-compatible streaming provider."""
from __future__ import annotations
from collections.abc import AsyncIterator, Sequence
from typing import Any
from openai import AsyncOpenAI
from boltpy.config import Settings, require_api_key
Message = dict[str, str]

class OpenAICompatibleProvider:
    """Thin provider wrapper shared by headless and TUI modes."""
    def __init__(self, settings: Settings) -> None:
        kwargs: dict[str, Any] = {"api_key": require_api_key(settings)}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = settings.model
        self.temperature = settings.temperature
    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        response = await self.client.chat.completions.create(model=self.model, messages=list(messages), temperature=self.temperature, stream=True)
        async for chunk in response:
            if chunk.choices and (text := chunk.choices[0].delta.content):
                yield text
    async def close(self) -> None:
        await self.client.close()
