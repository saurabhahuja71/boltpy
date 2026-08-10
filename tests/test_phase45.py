"""Coverage for multi-provider config, plan mode, todos, options, and HTTP tools."""
from __future__ import annotations
import asyncio
import pytest
from typer.testing import CliRunner
from boltpy import cli
from boltpy.agent.core import Agent, AgentEvent
from boltpy.agent.permissions import PermissionDecision, PermissionMode, PermissionManager, PermissionRequest
from boltpy.agent.providers import OllamaProvider, OpenAICompatibleProvider, ProviderEvent, build_provider
from boltpy.agent.todos import todo_store
from boltpy.agent.tools import default_registry, http_request
from boltpy.config import Settings, load_settings
from boltpy.tui.app import BoltpyApp, OptionsPrompt


# --- Config ---

def test_config_supports_provider_theme_and_plan_mode():
    settings = Settings(provider="openrouter", theme="light", permission_mode="plan")
    assert settings.provider == "openrouter"
    assert settings.theme == "light"
    assert settings.permission_mode == "plan"

def test_config_env_variables_for_provider_and_theme(monkeypatch):
    monkeypatch.setenv("BOLTPY_PROVIDER", "ollama")
    monkeypatch.setenv("BOLTPY_THEME", "light")
    settings = load_settings()
    assert settings.provider == "ollama"
    assert settings.theme == "light"


# --- Providers ---

def test_build_provider_returns_ollama_for_ollama():
    assert isinstance(build_provider(Settings(provider="ollama")), OllamaProvider)

def test_build_provider_defaults_to_openai_compatible():
    assert isinstance(build_provider(Settings(provider="openrouter", api_key="k")), OpenAICompatibleProvider)
    assert build_provider(Settings(provider="openrouter", api_key="k")).provider_name == "openrouter"


# --- Plan mode ---

@pytest.mark.asyncio
async def test_plan_mode_denies_capability_tools_and_allows_read_only():
    manager = PermissionManager(mode=PermissionMode.PLAN)
    request = default_registry().get("run_shell").permission_request({"command": "echo hi"})
    assert request is not None
    assert await manager.authorize(request) == PermissionDecision.DENY
    read_request = PermissionRequest("read_file", "", {"path": "."})
    assert await manager.authorize(read_request) == PermissionDecision.ALLOW_ONCE

def test_plan_mode_adds_guidance_to_system_prompt():
    agent = Agent(Settings(api_key="k", permission_mode="plan"))
    assert "PLAN mode" in agent.messages[0]["content"]

def test_set_permission_mode_updates_guidance():
    agent = Agent(Settings(api_key="k"))
    assert "PLAN mode" not in agent.messages[0]["content"]
    agent.set_permission_mode(PermissionMode.PLAN)
    assert "PLAN mode" in agent.messages[0]["content"]
    agent.set_permission_mode(PermissionMode.ALLOW)
    assert "PLAN mode" not in agent.messages[0]["content"]


# --- Todos ---

@pytest.fixture(autouse=True)
def clean_todos():
    todo_store.clear()
    yield
    todo_store.clear()

@pytest.mark.asyncio
async def test_todo_tools_add_complete_and_list():
    registry = default_registry()
    added = await registry.execute("add_todo", {"description": "fix the bug"})
    assert added.ok and "fix the bug" in added.output
    listed = await registry.execute("list_todos", {})
    assert listed.ok and "[ ] 1. fix the bug" in listed.output
    completed = await registry.execute("complete_todo", {"todo_id": "1"})
    assert completed.ok
    listed = await registry.execute("list_todos", {})
    assert "[x] 1. fix the bug" in listed.output


# --- HTTP tool ---

class FakeResponse:
    status_code = 200
    text = '{"ok": true}'

class FakeClient:
    def __init__(self, error=None):
        self.error = error
        self.captured = {}
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def request(self, method, url, **kwargs):
        self.captured.update(method=method, url=url, kwargs=kwargs)
        if self.error is not None:
            raise self.error
        return FakeResponse()

def _fake_async_client(monkeypatch, error=None):
    fake = FakeClient(error)
    monkeypatch.setattr("boltpy.agent.tools.httpx.AsyncClient", lambda **kw: fake)
    return fake

@pytest.mark.asyncio
async def test_http_request_success(monkeypatch):
    fake = _fake_async_client(monkeypatch)
    result = await http_request("GET", "https://example.com")
    assert result.ok
    assert result.exit_code == 200
    assert fake.captured["method"] == "GET"

@pytest.mark.asyncio
async def test_http_request_timeout_is_clear(monkeypatch):
    import httpx
    _fake_async_client(monkeypatch, error=httpx.TimeoutException("slow"))
    result = await http_request("GET", "https://example.com", timeout=1)
    assert not result.ok
    assert "timed out" in result.error
    assert result.timed_out

@pytest.mark.asyncio
async def test_http_request_rejects_bad_url():
    with pytest.raises(ValueError):
        await http_request("GET", "not-a-url")


# --- Options picker (agent) ---

class OptionsProvider:
    def __init__(self, name="present_options"):
        self.name = name
        self.turn = 0
    async def stream_response(self, messages, tools):
        if self.turn == 0:
            self.turn += 1
            yield ProviderEvent("tool_call", call_id="call-1", name=self.name, arguments='{"title": "Pick", "options": ["A", "B", "C"]}')
        else:
            yield ProviderEvent("text", text="chosen")
    async def close(self):
        pass

@pytest.mark.asyncio
async def test_present_options_uses_interactive_handler():
    agent = Agent(Settings(api_key="k", permission_mode="allow"), provider=OptionsProvider())
    captured = {}
    async def handler(title, options, allow_custom):
        captured.update(title=title, options=options, allow_custom=allow_custom)
        return "B"
    agent.options_handler = handler
    events = [event async for event in agent.stream_events("pick one")]
    result = next(event.result for event in events if event.kind == "tool_result")
    assert result.ok and result.output == "B"
    assert captured == {"title": "Pick", "options": ["A", "B", "C"], "allow_custom": True}

@pytest.mark.asyncio
async def test_present_options_headless_picks_first():
    agent = Agent(Settings(api_key="k", permission_mode="allow"), provider=OptionsProvider())
    events = [event async for event in agent.stream_events("pick one")]
    result = next(event.result for event in events if event.kind == "tool_result")
    assert result.ok and result.output == "A"


# --- CLI flags ---

def test_cli_ask_respects_model_and_provider_flags(monkeypatch):
    captured = {}
    class FakeAgent:
        def __init__(self, settings, **kwargs):
            captured["settings"] = settings
        async def stream_events(self, prompt):
            yield AgentEvent("text", text="ok")
        async def stream(self, prompt):
            yield "ok"
        async def close(self):
            pass
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    result = CliRunner().invoke(cli.app, ["ask", "hi", "--model", "m1", "--provider", "ollama"])
    assert result.exit_code == 0
    assert captured["settings"].model == "m1"
    assert captured["settings"].provider == "ollama"


# --- TUI: status bar, options picker, todo panel ---

@pytest.mark.asyncio
async def test_status_bar_shows_provider_model_and_tokens():
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test", provider="openrouter", model="deepseek-r1"))
    async with app.run_test():
        app.agent.provider.total_tokens = 42
        app._set_status("Ready")
        rendered = str(app.query_one("#status", Static).render())
        assert "Mode: ASK" in rendered
        assert "Model: openrouter/deepseek-r1" in rendered
        assert "Tokens: 42" in rendered

@pytest.mark.asyncio
async def test_options_picker_selects_numbered_option_and_custom_answer():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        task = asyncio.create_task(app._request_options("Pick", ["Alpha", "Beta"], True))
        await pilot.pause()
        prompt = app.query_one(OptionsPrompt)
        assert prompt.display
        await pilot.press("2")
        await pilot.pause()
        assert task.done() and task.result() == "Beta"

@pytest.mark.asyncio
async def test_options_picker_custom_typed_answer():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        task = asyncio.create_task(app._request_options("Pick", ["Alpha"], True))
        await pilot.pause()
        prompt = app.query_one(OptionsPrompt)
        await pilot.press("down")
        await pilot.press("enter")
        assert prompt.query_one("#options-custom").has_focus
        await pilot.press("c", "u", "s", "t")
        await pilot.press("enter")
        await pilot.pause()
        assert task.done() and task.result() == "cust"

@pytest.mark.asyncio
async def test_todo_panel_renders_open_and_completed_items():
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        todo_store.add("first")
        todo_store.add("second")
        todo_store.complete("1")
        panel = app.query_one("#todo-panel", Static)
        panel.refresh_todos()
        rendered = str(panel.render())
        assert "[x] 1. first" in rendered
        assert "[ ] 2. second" in rendered
