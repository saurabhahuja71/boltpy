"""Provider abstraction with OpenAI-compatible and Ollama implementations."""
from __future__ import annotations
import base64
import mimetypes
import os
from pathlib import Path
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any
from openai import AsyncOpenAI
import httpx
from boltpy.config import Settings, require_api_key
Message = dict[str, Any]


class ProviderCapabilityError(RuntimeError):
    """The configured provider/model cannot perform the requested capability."""


def _image_data_url(image_path: Path) -> str:
    media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"

@dataclass
class ProviderEvent:
    """One streamed assistant text fragment or completed tool call."""
    kind: str
    text: str = ""
    call_id: str = ""
    name: str = ""
    arguments: str = ""

class Provider(ABC):
    """Common interface for streamed chat providers."""
    provider_name: str = "generic"
    model: str
    temperature: float
    total_tokens: int = 0

    @abstractmethod
    async def stream_response(self, messages: Sequence[Message], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[ProviderEvent]:
        """Yield text fragments and completed tool calls."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return models advertised by the provider."""

    @abstractmethod
    async def health_check(self) -> tuple[bool, str]:
        """Return connection status and a user-facing explanation."""

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Compatibility text-only stream."""
        async for event in self.stream_response(messages):
            if event.kind == "text":
                yield event.text

    async def analyze_image(self, image_path: Path, prompt: str) -> str:
        """Analyze one image, or report that this provider cannot do so."""
        raise ProviderCapabilityError(
            f"Provider {self.provider_name!r} has no configured image-analysis transport"
        )

    async def close(self) -> None:
        """Release client resources."""

class _OpenAICompatibleBase(Provider):
    """Shared streaming logic for OpenAI-compatible APIs."""
    _supports_usage_chunks = True

    def __init__(self, settings: Settings) -> None:
        self.model = settings.model
        self.temperature = settings.temperature
        self.total_tokens = 0
        self._saw_usage = False

    async def stream_response(self, messages: Sequence[Message], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[ProviderEvent]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": list(messages), "temperature": self.temperature, "stream": True}
        if tools:
            kwargs["tools"] = tools
        if self._supports_usage_chunks:
            kwargs["stream_options"] = {"include_usage": True}
        response = await self.client.chat.completions.create(**kwargs)
        calls: dict[int, dict[str, str]] = {}
        async for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None and getattr(usage, "total_tokens", None) is not None:
                self.total_tokens = usage.total_tokens
                self._saw_usage = True
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                self._estimate_tokens(delta.content)
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

    async def analyze_image(self, image_path: Path, prompt: str) -> str:
        """Send a standard OpenAI multimodal message for an explicitly enabled model."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
            ]}],
            temperature=self.temperature,
            stream=False,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ProviderCapabilityError(
                f"Provider/model {self.provider_name}/{self.model} returned no image analysis"
            )
        return content.strip()

    async def list_models(self) -> list[str]:
        response = await self.client.models.list()
        return [item.id for item in response.data]

    async def health_check(self) -> tuple[bool, str]:
        try:
            await self.list_models()
            return True, "Connected"
        except Exception as error:
            return False, str(error)

    def _estimate_tokens(self, text: str) -> None:
        """Rough token fallback for providers that do not emit usage chunks."""
        if not self._saw_usage:
            self.total_tokens += max(1, len(text) // 4)

    async def close(self) -> None:
        await self.client.close()

class OpenAICompatibleProvider(_OpenAICompatibleBase):
    """Any OpenAI-compatible API: OpenAI, OpenRouter, xAI, DeepSeek, vLLM, SGLang…"""
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.provider_name = (settings.provider or "openai").lower()
        kwargs: dict[str, Any] = {"api_key": require_api_key(settings)}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self.client = AsyncOpenAI(**kwargs)

class OllamaProvider(_OpenAICompatibleBase):
    """Local Ollama daemon through its OpenAI-compatible endpoint."""
    provider_name = "ollama"
    _supports_usage_chunks = False

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        base_url = settings.base_url or os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
        base_url = base_url.rstrip("/")
        self.ollama_url = base_url.removesuffix("/v1")
        self.client = AsyncOpenAI(api_key=settings.api_key or "ollama", base_url=base_url if base_url.endswith("/v1") else base_url + "/v1")

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(self.ollama_url + "/api/tags")
            response.raise_for_status()
            return [str(item["name"]) for item in response.json().get("models", []) if item.get("name")]

    async def analyze_image(self, image_path: Path, prompt: str) -> str:
        """Use Ollama's native /api/chat image format for vision models."""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [
                base64.b64encode(image_path.read_bytes()).decode("ascii")
            ]}],
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self.ollama_url + "/api/chat", json=payload)
                response.raise_for_status()
                content = response.json().get("message", {}).get("content")
        except httpx.HTTPError as error:
            raise ProviderCapabilityError(
                f"Ollama model {self.model!r} rejected image analysis: {error}"
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderCapabilityError(
                f"Ollama model {self.model!r} returned no image analysis"
            )
        return content.strip()

    async def health_check(self) -> tuple[bool, str]:
        try:
            models = await self.list_models()
            return True, f"Connected ({len(models)} models)"
        except Exception as error:
            return False, f"Ollama unavailable at {self.ollama_url}: {error}"

def build_provider(settings: Settings) -> Provider:
    """Construct the provider named by the settings."""
    if (settings.provider or "").lower() == "ollama":
        return OllamaProvider(settings)
    return OpenAICompatibleProvider(settings)
