"""Focused Phase 3 presentation and theme regression tests."""
from __future__ import annotations
import pytest
from textual.widgets import Footer, Markdown
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp, ConversationLog, ModelPrompt, PermissionPrompt, render_markdown


def test_markdown_renderer_returns_textual_markdown_for_common_content():
    content = """# Heading

- **bold** and `inline code`
- [link](https://example.com)

```python
def hello():
    return \"hi\"
```

| name | value |
| --- | --- |
| one | 1 |
"""
    rendered = render_markdown(content)
    assert isinstance(rendered, Markdown)

@pytest.mark.asyncio
async def test_theme_command_switches_screen_immediately():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert app.mouse_mode == "interactive"
        assert app.theme_name == "light"
        await app._submit_prompt("/theme light")
        assert app.theme_name == "light"
        await app._submit_prompt("/theme dark")
        assert app.theme_name == "dark"

@pytest.mark.asyncio
async def test_help_documents_phase3_commands_and_controls():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        await app._submit_prompt("/help")
        assert app.query_one(ConversationLog).children
        assert app.query_one(PermissionPrompt).display is False

@pytest.mark.asyncio
async def test_alt_p_shows_all_commands_without_vscode_palette_conflict():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.press("alt+p")
        await pilot.pause()
        assert ("alt+p", "show_commands", "Show commands") in app.BINDINGS
        rendered = str(app.query_one(ConversationLog).children[-1].render())
        assert "/permissions remove <command>" in rendered
        assert "Alt+P commands" in rendered
        assert "Ctrl+Shift+M mode" in rendered

@pytest.mark.asyncio
async def test_cancel_shortcut_is_first_in_compact_footer():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        footer = app.query_one(Footer)
        assert app.BINDINGS[0] == ("ctrl+c", "cancel_operation", "Cancel operation")
        assert footer.compact
        assert not footer.show_command_palette

@pytest.mark.asyncio
async def test_ctrl_shift_m_cycles_permission_modes():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        assert app.permissions.mode.value == "ask"
        await pilot.press("ctrl+shift+m")
        assert app.permissions.mode.value == "allow"
        await pilot.press("ctrl+shift+m")
        assert app.permissions.mode.value == "plan"
        await pilot.press("ctrl+shift+m")
        assert app.permissions.mode.value == "ask"
        assert ("ctrl+shift+m", "toggle_mode", "Change permission mode") in app.BINDINGS
        assert ("ctrl+shift+t", "toggle_todo", "Toggle todos") in app.BINDINGS
        assert ("ctrl+shift+i", "toggle_mouse", "Toggle interactive cursor") in app.BINDINGS

@pytest.mark.asyncio
async def test_alt_p_shows_commands_when_prompt_is_empty():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.press("alt+p")
        await pilot.pause()
        assert "/help  show commands and controls" in str(app.query_one(ConversationLog).children[-1].render())


@pytest.mark.asyncio
async def test_mouse_select_mode_releases_terminal_reporting_and_restores_it(monkeypatch):
    class DriverProbe:
        def __init__(self): self.calls = []
        def _disable_mouse_support(self): self.calls.append("disable")
        def _enable_mouse_support(self): self.calls.append("enable")
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        probe = DriverProbe()
        monkeypatch.setattr(app._driver, "_disable_mouse_support", probe._disable_mouse_support, raising=False)
        monkeypatch.setattr(app._driver, "_enable_mouse_support", probe._enable_mouse_support, raising=False)
        await app._submit_prompt("/mouse select")
        assert app.mouse_mode == "select"
        await app._submit_prompt("/mouse interactive")
        assert app.mouse_mode == "interactive"
        assert probe.calls == ["disable", "enable"]


@pytest.mark.asyncio
async def test_model_selector_changes_provider_model_and_supports_keyboard():
    app = BoltpyApp(Settings(api_key="test", model="first", models=["second", "third"]))
    async with app.run_test() as pilot:
        await app._submit_prompt("/model")
        selector = app.query_one(ModelPrompt)
        assert selector.display
        await pilot.press("down")
        await pilot.press("enter")
        assert app.settings.model == "second"
        assert app.agent.provider.model == "second"
        assert not selector.display


@pytest.mark.asyncio
async def test_current_working_directory_is_visible_near_top_of_screen():
    from pathlib import Path
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        cwd = app.query_one("#cwd", Static)
        assert str(cwd.render()) == f"CWD: {Path.cwd()}"
        assert cwd.region.y < app.query_one("#transcript").region.y


@pytest.mark.asyncio
async def test_model_selector_discovers_local_ollama_models(monkeypatch):
    class Process:
        returncode = 0
        async def communicate(self):
            return b"NAME ID SIZE MODIFIED\nqwen3-coder:30b abc 18 GB today\nveriloop-coder-e1:latest def 16 GB today\n", b""
    async def fake_exec(*args, **kwargs):
        assert args == ("ollama", "list")
        return Process()
    monkeypatch.setattr("boltpy.tui.app.asyncio.create_subprocess_exec", fake_exec)
    app = BoltpyApp(Settings(api_key="test", model="configured"))
    async with app.run_test():
        assert await app._available_models() == ["configured", "qwen3-coder:30b", "veriloop-coder-e1:latest"]
