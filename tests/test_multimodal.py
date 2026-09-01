import base64

import pytest

from boltpy.agent.providers import ProviderCapabilityError
from boltpy.agent.session import SessionStore
from boltpy.agent.tools import ToolResult, analyze_image, default_registry
from boltpy.agent.coding import Workspace
from boltpy.config import Settings


class VisionProvider:
    provider_name = "fake"
    model = "vision-model"

    def __init__(self, result="A screenshot with a blue panel"):
        self.result = result
        self.calls = []

    async def analyze_image(self, path, prompt):
        self.calls.append((path, prompt))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def image_path(tmp_path, suffix=".png"):
    path = tmp_path / f"screen{suffix}"
    path.write_bytes(b"small image bytes")
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [None, False])
async def test_vision_disabled_or_unknown_refuses_without_provider_call(tmp_path, enabled):
    image_path(tmp_path)
    provider = VisionProvider()
    result = await analyze_image("screen.png", "describe it", Workspace(tmp_path), provider, enabled)
    assert not result.ok
    assert "not inspected" in result.error
    assert not provider.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg", ".webp"])
async def test_enabled_analysis_accepts_supported_formats(tmp_path, suffix):
    path = image_path(tmp_path, suffix)
    provider = VisionProvider()
    result = await analyze_image(path.name, "describe it", Workspace(tmp_path), provider, True)
    assert result == ToolResult(True, output="A screenshot with a blue panel")
    assert provider.calls == [(path, "describe it")]


@pytest.mark.asyncio
async def test_provider_model_rejection_is_structured(tmp_path):
    image_path(tmp_path)
    provider = VisionProvider(ProviderCapabilityError("model does not accept images"))
    result = await analyze_image("screen.png", "describe it", Workspace(tmp_path), provider, True)
    assert not result.ok
    assert "provider/model" in result.error
    assert "does not accept images" in result.error


@pytest.mark.asyncio
async def test_image_validation_errors_are_actionable(tmp_path):
    provider = VisionProvider()
    missing = await analyze_image("missing.png", "describe", Workspace(tmp_path), provider, True)
    unsupported_path = tmp_path / "screen.txt"
    unsupported_path.write_text("not image")
    unsupported = await analyze_image("screen.txt", "describe", Workspace(tmp_path), provider, True)
    outside_path = tmp_path.parent / "outside.png"
    outside_path.write_bytes(b"image")
    outside = await analyze_image(str(outside_path), "describe", Workspace(tmp_path), provider, True)
    assert "does not exist" in missing.error
    assert "Unsupported image type" in unsupported.error
    assert "outside the permitted workspace" in outside.error
    assert not provider.calls


@pytest.mark.asyncio
async def test_oversized_image_is_rejected_before_provider(tmp_path):
    path = image_path(tmp_path)
    with path.open("ab") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    provider = VisionProvider()
    result = await analyze_image(path.name, "describe", Workspace(tmp_path), provider, True)
    assert not result.ok
    assert "too large" in result.error
    assert not provider.calls


def test_analyze_image_is_registered_only_with_provider(tmp_path):
    assert "analyze_image" not in {schema["function"]["name"] for schema in default_registry(tmp_path).schemas()}
    registry = default_registry(tmp_path, VisionProvider(), True)
    assert "analyze_image" in {schema["function"]["name"] for schema in registry.schemas()}


def test_image_analysis_result_does_not_persist_payload(tmp_path):
    raw = b"secret image bytes"
    encoded = base64.b64encode(raw).decode()
    result = ToolResult(True, output="Visual analysis only")
    messages = [{"role": "tool", "content": result.as_message()}]
    SessionStore(tmp_path).save(messages)
    saved = (tmp_path / ".bolt" / "sessions" / "latest.json").read_text()
    assert encoded not in saved
    assert encoded not in result.as_message()


def test_text_only_provider_configuration_remains_unchanged():
    settings = Settings(provider="ollama", model="llama3", vision_enabled=None)
    assert settings.vision_enabled is None


class CompletionResponse:
    class Choice:
        class Message:
            content = "native analysis"
        message = Message()
    choices = [Choice()]


class CompletionClient:
    class Chat:
        class Completions:
            def __init__(self, owner):
                self.owner = owner
            async def create(self, **kwargs):
                self.owner.kwargs = kwargs
                return CompletionResponse()
        def __init__(self, owner):
            self.completions = self.Completions(owner)
    def __init__(self):
        self.chat = self.Chat(self)


@pytest.mark.asyncio
async def test_openai_compatible_transport_uses_standard_transient_image_content(tmp_path):
    from boltpy.agent.providers import _OpenAICompatibleBase
    path = image_path(tmp_path, ".jpg")
    provider = _OpenAICompatibleBase.__new__(_OpenAICompatibleBase)
    provider.model = "explicit-vision-model"
    provider.temperature = 0.2
    provider.client = CompletionClient()
    result = await provider.analyze_image(path, "describe")
    content = provider.client.kwargs["messages"][0]["content"]
    assert result == "native analysis"
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


class NativeResponse:
    def raise_for_status(self):
        pass
    def json(self):
        return {"message": {"content": "ollama analysis"}}


class NativeClient:
    def __init__(self, owner):
        self.owner = owner
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def post(self, url, json):
        self.owner.request = (url, json)
        return NativeResponse()


@pytest.mark.asyncio
async def test_ollama_transport_uses_native_chat_image_format(tmp_path, monkeypatch):
    from boltpy.agent.providers import OllamaProvider
    path = image_path(tmp_path, ".webp")
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.model = "llava"
    provider.temperature = 0.2
    provider.ollama_url = "http://ollama:11434"
    monkeypatch.setattr("boltpy.agent.providers.httpx.AsyncClient", lambda **kwargs: NativeClient(provider))
    result = await provider.analyze_image(path, "describe")
    url, payload = provider.request
    assert result == "ollama analysis"
    assert url == "http://ollama:11434/api/chat"
    assert payload["messages"][0]["content"] == "describe"
    assert payload["messages"][0]["images"] == [base64.b64encode(path.read_bytes()).decode("ascii")]
