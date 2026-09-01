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
from boltpy.tui.app import BoltpyApp, OptionsPrompt, _needs_task_todo


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

def test_system_prompt_explains_when_to_use_todos():
    agent = Agent(Settings(api_key="k"))
    prompt = agent.messages[0]["content"]
    assert "add_todo" in prompt
    assert "Do not create todos for simple questions" in prompt

def test_system_prompt_sets_remote_tool_discipline():
    agent = Agent(Settings(api_key="k"))
    prompt = agent.messages[0]["content"]
    assert "literal host, user, and command" in prompt
    assert "Never claim an operation succeeded" in prompt

def test_multi_action_prompts_get_automatic_task_tracking():
    assert _needs_task_todo("go to podman9 and stop the containers")
    assert _needs_task_todo("use the remote machine with the requested account and report the current service state")
    assert _needs_task_todo("V")

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
    import json
    added = await registry.execute("add_todo", {"description": "fix the bug"})
    assert added.ok and "fix the bug" in added.output
    todo_id = json.loads(added.output)["id"]
    assert todo_id.startswith("todo_")
    listed = await registry.execute("list_todos", {})
    assert listed.ok and f"[ ] {todo_id}. fix the bug" in listed.output
    updated = await registry.execute("update_todo", {"todo_id": todo_id, "description": "updated bug"})
    assert updated.ok and todo_id in updated.output
    completed = await registry.execute("complete_todo", {"todo_id": todo_id})
    assert completed.ok
    listed = await registry.execute("list_todos", {})
    assert f"[x] {todo_id}. updated bug" in listed.output


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
        assert "Permission Mode: ASK" in rendered
        assert "Mouse Mode: SELECT" in rendered
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
        await pilot.pause()
        assert app.query_one("#prompt").has_focus

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
        await pilot.pause()
        assert app.query_one("#prompt").has_focus

@pytest.mark.asyncio
async def test_todo_panel_renders_open_and_completed_items():
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        todo_store.add("first")
        todo_store.add("second")
        todo_store.complete(todo_store.items()[0].id)
        panel = app.query_one("#todo-panel", Static)
        panel.refresh_todos()
        rendered = str(panel.render())
        assert "[x] 1. first" in rendered


# --- Layout: single transcript + todo sidebar ---

@pytest.mark.asyncio
async def test_layout_has_one_transcript_and_no_duplicate_output_area():
    from textual.containers import Horizontal
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        content = app.query_one("#content", Horizontal)
        assert len(content.query("#transcript")) == 1
        assert len(content.query("#todo-panel")) == 1
        assert len(app.query("#streaming")) == 0
        assert len(app.query("#transcript")) == 1

@pytest.mark.asyncio
async def test_hiding_todo_panel_lets_transcript_take_full_width():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        panel = app.query_one("#todo-panel")
        assert panel.display
        app.action_toggle_todo()
        await pilot.pause()
        assert not panel.display

@pytest.mark.asyncio
async def test_streaming_writes_into_transcript_not_standalone_widget():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = SlowAgent(app)
        fake.release.set()
        app.agent = fake
        worker = app._ask("hello")
        await pilot.pause()
        await fake.gate.wait()
        fake.release.set()
        await worker.wait()
        streaming = app.query_one(".assistant-streaming")
        assert streaming.parent is app.query_one("#transcript")
        assert "hello" in streaming.source


# --- Queue and interrupt ---

class SlowAgent:
    def __init__(self, app) -> None:
        self.app = app
        self.runs: list[str] = []
        self.gate = asyncio.Event()
        self.release = asyncio.Event()
    async def stream_events(self, prompt: str):
        self.runs.append(prompt)
        self.gate.set()
        await self.release.wait()
        yield AgentEvent("text", text=f"done: {prompt}")
    async def close(self) -> None:
        pass

@pytest.mark.asyncio
async def test_prompts_queue_while_busy_and_run_in_order():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = SlowAgent(app)
        app.agent = fake
        app._active_worker = app._ask("first")
        await pilot.pause()
        await fake.gate.wait()
        assert app.busy
        await app._submit_prompt("second")
        await app._submit_prompt("third")
        assert app._prompt_queue == ["second", "third"]
        fake.release.set()
        await app._active_worker.wait()
        assert fake.runs == ["first", "second", "third"]
        assert not app.busy
        assert app._status_state == "ready"

@pytest.mark.asyncio
async def test_interrupt_cancels_running_worker_but_keeps_queue():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = SlowAgent(app)
        app.agent = fake
        app._prompt_queue = ["queued-one", "queued-two"]
        app._active_worker = app._ask("first")
        await pilot.pause()
        await fake.gate.wait()
        app.action_cancel_operation()
        await pilot.pause()
        # the current prompt is cancelled but queued prompts survive and the next one starts
        assert app.busy
        assert fake.runs == ["first", "queued-one"]
        assert app._prompt_queue == ["queued-two"]
        fake.release.set()
        await app._active_worker.wait()
        assert fake.runs == ["first", "queued-one", "queued-two"]
        assert not app.busy
        assert app._prompt_queue == []

@pytest.mark.asyncio
async def test_queue_command_lists_queued_prompts():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        app._prompt_queue = ["alpha", "beta"]
        await app._submit_prompt("/queue")
        await pilot.pause()
        rendered = " ".join(str(widget.render()) for widget in app.query("#transcript .system-message"))
        assert "1. alpha" in rendered
        assert "2. beta" in rendered


def test_cli_version_and_short_help():
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("Bolt ")
    result = CliRunner().invoke(cli.app, ["-h"])
    assert result.exit_code == 0
    assert "A terminal coding agent" in result.stdout


def test_cli_rejects_invalid_workspace():
    result = CliRunner().invoke(cli.app, ["--project", "/path/that/does/not/exist"])
    assert result.exit_code == 2
    assert "workspace does not exist" in result.output


@pytest.mark.asyncio
async def test_multiple_todos_complete_out_of_order():
    import json
    registry = default_registry()
    ids = [json.loads((await registry.execute("add_todo", {"description": f"step {i}"})).output)["id"] for i in range(4)]
    assert len(set(ids)) == 4
    assert await registry.execute("update_todo", {"todo_id": ids[1], "description": "updated step"})
    assert await registry.execute("complete_todo", {"todo_id": ids[3]})
    assert await registry.execute("complete_todo", {"todo_id": ids[0]})
    assert await registry.execute("complete_todo", {"todo_id": ids[2]})
    invalid = await registry.execute("update_todo", {"todo_id": "todo_1", "description": "invalid"})
    assert not invalid.ok and "todo_1" in invalid.error
    assert todo_store.open_count() == 1
