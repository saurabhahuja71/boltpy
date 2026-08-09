"""Focused Phase 3 presentation and theme regression tests."""
from __future__ import annotations
import pytest
from rich.markdown import Markdown
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp, ConversationLog, ModelPrompt, PermissionPrompt, render_markdown


def test_markdown_renderer_returns_rich_markdown_for_common_content():
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
    assert rendered.code_theme == "monokai"

@pytest.mark.asyncio
async def test_theme_command_switches_screen_immediately():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert app.mouse_mode == "select"
        await app._submit_prompt("/theme light")
        assert app.theme_name == "light"
        assert app.screen.has_class("light")
        await app._submit_prompt("/theme dark")
        assert app.theme_name == "dark"
        assert not app.screen.has_class("light")

@pytest.mark.asyncio
async def test_help_documents_phase3_commands_and_controls():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        await app._submit_prompt("/help")
        assert app.query_one(ConversationLog).lines
        assert app.query_one(PermissionPrompt).display is False

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
async def test_current_working_directory_is_visible_and_copyable_line_exists():
    from pathlib import Path
    from textual.widgets import Static
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test():
        assert str(app.query_one("#cwd", Static).render()) == f"CWD: {Path.cwd()}"


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
