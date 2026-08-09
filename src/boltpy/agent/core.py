"""Conversation state and the basic Boltpy agent loop."""
from __future__ import annotations
from collections.abc import AsyncIterator
from boltpy.agent.providers import Message, OpenAICompatibleProvider
from boltpy.config import Settings

class Agent:
    """A minimal history-aware streaming agent without tools."""
    def __init__(self, settings: Settings, provider: OpenAICompatibleProvider | None = None) -> None:
        self.settings = settings
        self.provider = provider or OpenAICompatibleProvider(settings)
        self.messages: list[Message] = [{"role": "system", "content": settings.system_prompt}]
    async def stream(self, prompt: str) -> AsyncIterator[str]:
        self.messages.append({"role": "user", "content": prompt})
        parts: list[str] = []
        try:
            async for token in self.provider.stream(self.messages):
                parts.append(token)
                yield token
        except Exception:
            self.messages.pop()
            raise
        self.messages.append({"role": "assistant", "content": "".join(parts)})
    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self.settings.system_prompt}]
    async def close(self) -> None:
        await self.provider.close()
