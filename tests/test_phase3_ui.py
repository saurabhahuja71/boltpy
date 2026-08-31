"""Focused Phase 3 presentation and theme regression tests."""
from __future__ import annotations
import pytest
from textual.widgets import Footer, Markdown
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp, ConversationLog, ModelPrompt, OptionsPrompt, PermissionPrompt, render_markdown


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
        assert app.theme_name == "dark"
        assert app.settings.theme == "dark"
        await app._submit_prompt("/theme light")
        assert app.theme_name == "light"
        await app._submit_prompt("/theme dark")
        assert app.theme_name == "dark"


@pytest.mark.asyncio
async def test_theme_command_opens_picker_and_applies_selection():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await app._submit_prompt("/theme")
        await pilot.pause()
        picker = app.query_one(OptionsPrompt)
        assert picker.display
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.theme_name == "light"
        assert not picker.display


@pytest.mark.asyncio
async def test_slash_input_shows_command_suggestions():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.text = "/th"
        await pilot.pause()
        suggestions = app.query_one("#command-suggestions")
        assert suggestions.display
        assert "/theme" in str(suggestions.render())


@pytest.mark.asyncio
async def test_normal_command_characters_are_not_treated_as_shortcuts():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.text = "/c"
        await pilot.pause()
        assert prompt.text == "/c"


@pytest.mark.asyncio
async def test_help_documents_phase3_commands_and_controls():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        await app._submit_prompt("/help")
        assert app.query_one(ConversationLog).children
        assert app.query_one(PermissionPrompt).display is False

@pytest.mark.asyncio
async def test_alt_r_shows_all_commands_without_vscode_palette_conflict():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert ("ctrl+g", "show_commands", "Show commands") in app.BINDINGS
        rendered = str(app.query_one(ConversationLog).children[-1].render())
        assert "/permissions remove <command>" in rendered
        assert "Commands Ctrl+G" in rendered
        assert "Theme Ctrl+P" in rendered

@pytest.mark.asyncio
async def test_cancel_shortcut_is_first_in_compact_footer():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        footer = app.query_one(Footer)
        assert app.BINDINGS[0] == ("ctrl+c", "cancel_operation", "Cancel operation")
        assert footer.compact
        assert not footer.show_command_palette

@pytest.mark.asyncio
async def test_alt_y_cycles_permission_modes():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        assert app.permissions.mode.value == "ask"
        await pilot.press("ctrl+m")
        assert app.permissions.mode.value == "allow"
        await pilot.press("ctrl+m")
        assert app.permissions.mode.value == "plan"
        await pilot.press("ctrl+m")
        assert app.permissions.mode.value == "ask"
        assert ("ctrl+m", "toggle_mode", "Change permission mode") in app.BINDINGS
        assert ("ctrl+t", "toggle_todo", "Toggle todos") in app.BINDINGS
        assert ("ctrl+i", "toggle_mouse", "Toggle interactive cursor") in app.BINDINGS

@pytest.mark.asyncio
async def test_alt_r_shows_commands_when_prompt_is_empty():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+g")
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
async def test_current_working_directory_is_not_rendered():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert not app.query("#cwd")
