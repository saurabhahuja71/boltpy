"""Focused Phase 3 presentation and theme regression tests."""
from __future__ import annotations
import pytest
from textual.widgets import Footer, Markdown
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp, ConversationLog, ModelPrompt, OptionsPrompt, PermissionPrompt, PromptTextArea, render_markdown


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
async def test_markdown_uses_compact_layout_without_mutating_source():
    from textual.widgets import Label

    content = "# Heading\n\nParagraph\n\n- item\n\n```python\ndef hello():\n    return 1\n```"
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        rendered = render_markdown(content)
        await app.query_one(ConversationLog).log(rendered)
        await rendered.update(content)
        assert rendered.source == content
        assert rendered.styles.padding.top == 0
        assert all(child.styles.margin.top == 0 and child.styles.margin.bottom == 0 for child in rendered.children)
        fence = next(child for child in rendered.children if child.__class__.__name__ == "MarkdownFence")
        assert fence.query_one(Label).styles.padding.top == 0
        assert fence.code == "def hello():\n    return 1"


@pytest.mark.asyncio
async def test_streaming_markdown_has_same_compact_presentation():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        transcript = app.query_one(ConversationLog)
        streaming = Markdown("", classes="assistant-streaming")
        final = render_markdown("final")
        await transcript.log(streaming)
        await transcript.log(final)
        assert streaming.styles.padding == final.styles.padding
        assert streaming.styles.margin == final.styles.margin
        assert [type(child) for child in transcript.children[-2:]] == [Markdown, Markdown]


@pytest.mark.asyncio
async def test_normal_messages_mount_without_spacer_widgets():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        transcript = app.query_one(ConversationLog)
        app._write("first")
        app._write("second")
        assert [type(child).__name__ for child in transcript.children[-2:]] == ["Static", "Static"]


@pytest.mark.asyncio
async def test_theme_command_switches_screen_immediately():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert app.mouse_mode == "select"
        assert "Mouse Mode: SELECT" in str(app.query_one("#status").render())
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
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert ("ctrl+o", "show_commands", "Commands") in app.BINDINGS
        rendered = str(app.query_one(ConversationLog).children[-1].render())
        assert "/permissions remove <command>" in rendered
        assert "Commands Ctrl+O" in rendered
        assert "Theme Ctrl+B" in rendered

@pytest.mark.asyncio
async def test_footer_starts_with_mode_mouse_and_vision_shortcuts():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        footer = app.query_one(Footer)
        assert app.BINDINGS[:3] == [
            ("ctrl+r", "toggle_mode", "Permission"),
            ("ctrl+l", "toggle_mouse", "Mouse"),
            ("ctrl+y", "toggle_vision", "Vision"),
        ]
        assert app.BINDINGS[-2:] == [("ctrl+c", "cancel_operation", "Cancel"), ("ctrl+q", "quit", "Quit")]
        assert not footer.compact
        assert not footer.show_command_palette

@pytest.mark.asyncio
async def test_alt_y_cycles_permission_modes():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        assert app.permissions.mode.value == "ask"
        await pilot.press("ctrl+r")
        assert app.permissions.mode.value == "allow"
        await pilot.press("ctrl+r")
        assert app.permissions.mode.value == "plan"
        await pilot.press("ctrl+r")
        assert app.permissions.mode.value == "ask"
        assert ("ctrl+r", "toggle_mode", "Permission") in app.BINDINGS
        assert ("ctrl+t", "toggle_todo", "Todos") in app.BINDINGS
        assert ("ctrl+l", "toggle_mouse", "Mouse") in app.BINDINGS
        footer = app.query_one(Footer)
        assert any(widget.key == "ctrl+r" and widget.description == "Permission" for widget in footer.query("*"))

@pytest.mark.asyncio
async def test_remap_is_suggested_and_lists_ctrl_y():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt")
        prompt.text = "/rem"
        await pilot.pause()
        assert "/remap" in str(app.query_one("#command-suggestions").render())

        prompt.text = "/remap"
        await pilot.press("enter")
        await pilot.pause()
        rendered = str(app.query_one(ConversationLog).children[-1].render())
        assert "ctrl+r  Permission" in rendered

@pytest.mark.asyncio
async def test_alt_r_shows_commands_when_prompt_is_empty():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")
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
        assert "Mouse Mode: INTERACTIVE" in str(app.query_one("#status").render())
        await app._submit_prompt("/mouse select")
        assert "Mouse Mode: SELECT" in str(app.query_one("#status").render())
        assert probe.calls == ["disable", "enable", "disable"]


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
async def test_prompt_is_focused_on_launch():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#prompt").has_focus


@pytest.mark.asyncio
async def test_footer_shows_workspace_and_ready_time():
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert "📁 " in str(app.query_one("#workspace", Static).render())
        assert str(app.query_one("#task-time", Static).render()) == "⏱ Ready"


def test_elapsed_time_formatting():
    assert BoltpyApp._format_elapsed(12.4) == "Time: 12.4s"
    assert BoltpyApp._format_elapsed(134.9) == "Time: 2m 14s"


def test_ctrl_v_remains_textual_paste_and_ctrl_y_is_vision_toggle():
    assert any(binding.key == "ctrl+v" and binding.action == "paste" for binding in PromptTextArea.BINDINGS)
    assert not any(binding[0] == "ctrl+v" for binding in BoltpyApp.BINDINGS)
    assert ("ctrl+y", "toggle_vision", "Vision") in BoltpyApp.BINDINGS


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "override", "expected"), [
    (True, None, True), (True, False, False),
    (False, None, False), (False, True, True),
    (None, None, None), (None, True, True),
])
async def test_effective_vision_state_precedence(tmp_path, configured, override, expected):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path, vision_enabled=configured))
    async with app.run_test():
        app._vision_override = override
        assert app.effective_vision_state() is expected


@pytest.mark.asyncio
async def test_vision_commands_are_local_and_ctrl_y_toggles(tmp_path):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path, vision_enabled=None))
    async with app.run_test() as pilot:
        async def unexpected_provider_call(_prompt):
            raise AssertionError("slash command reached provider")
        app.agent.stream_events = unexpected_provider_call
        await app._submit_prompt("/vision")
        assert "Vision: UNKNOWN" in str(app.query_one(ConversationLog).children[-1].render())
        await app._submit_prompt("/vision on")
        assert app.effective_vision_state() is True
        await app._submit_prompt("/vision off")
        assert app.effective_vision_state() is False
        await app._submit_prompt("/vision toggle")
        assert app.effective_vision_state() is True
        await app._submit_prompt("/vision invalid now")
        assert "Usage: /vision [on|off|toggle]" in str(app.query_one(ConversationLog).children[-1].render())
        app._vision_override = None
        await pilot.press("ctrl+y")
        assert app.effective_vision_state() is True


@pytest.mark.asyncio
async def test_status_panel_shows_vision_off_by_default_and_on_after_ctrl_y(tmp_path):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path, vision_enabled=None))
    async with app.run_test() as pilot:
        assert "Vision: OFF" in str(app.query_one("#status").render())
        await pilot.press("ctrl+y")
        assert "Vision: ON" in str(app.query_one("#status").render())


@pytest.mark.asyncio
@pytest.mark.parametrize("logical", [
    "sudo dnf install code -y",
    "def hello():\n    print(\"hello\")",
    "enabled: true\nmodel: qwen3-coder",
    '{"enabled": true}',
    "first line\n\nthird line",
    "a very long logical line that must remain one line without display wrapping",
])
async def test_copy_uses_exact_latest_logical_assistant_text(tmp_path, logical):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path))
    copied = []
    async with app.run_test():
        app.agent.messages = [{"role": "system", "content": "system"}, {"role": "assistant", "content": logical}]
        app.copy_to_clipboard = copied.append
        await app._submit_prompt("/copy")
        assert copied == [logical]
        assert "Copied latest output to clipboard." in str(app.query_one(ConversationLog).children[-1].render())


@pytest.mark.asyncio
async def test_copy_prefers_latest_assistant_then_tool_logical_content(tmp_path):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path))
    copied = []
    async with app.run_test():
        app.agent.messages = [
            {"role": "assistant", "content": "older"},
            {"role": "tool", "content": "3 passed"},
        ]
        app.copy_to_clipboard = copied.append
        await app._submit_prompt("/copy")
        assert copied == ["3 passed"]
        app.agent.messages.append({"role": "assistant", "content": "new answer"})
        await app._submit_prompt("/copy")
        assert copied == ["3 passed", "new answer"]


@pytest.mark.asyncio
async def test_copy_without_output_and_clipboard_failure_are_reported(tmp_path):
    app = BoltpyApp(Settings(api_key="test", workspace=tmp_path))
    async with app.run_test():
        await app._submit_prompt("/copy")
        assert "Nothing to copy yet." in str(app.query_one(ConversationLog).children[-1].render())
        app.agent.messages = [{"role": "assistant", "content": "output"}]
        def fail(_text):
            raise OSError("clipboard unavailable")
        app.copy_to_clipboard = fail
        await app._submit_prompt("/copy")
        rendered = str(app.query_one(ConversationLog).children[-1].render())
        assert "Could not copy output to clipboard: clipboard unavailable" in rendered
