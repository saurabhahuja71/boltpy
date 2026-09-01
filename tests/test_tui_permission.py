"""Regression coverage for Textual's worker-only awaited screens."""
from __future__ import annotations
import pytest
import asyncio
from boltpy.agent.core import AgentEvent
from boltpy.agent.permissions import PermissionDecision, PermissionRequest
from boltpy.agent.tools import ToolResult, run_shell
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp, PermissionPrompt

class PermissionAgent:
    def __init__(self, app: BoltpyApp) -> None:
        self.app = app
        self.executed = False
    async def stream_events(self, prompt: str):
        request = PermissionRequest("run_shell", "shell.execute", {"command": "ls -la"})
        yield AgentEvent("tool_call", name="run_shell", arguments=request.arguments, status="requested")
        yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status="waiting")
        decision = await self.app.permissions.authorize(request)
        if decision == PermissionDecision.DENY:
            yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status="deny")
            yield AgentEvent("tool_result", name="run_shell", result=ToolResult(False, error="Permission denied"), status="failed")
        else:
            self.executed = True
            output = await run_shell(request.arguments["command"])
            yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status=decision.value)
            yield AgentEvent("tool_result", name="run_shell", result=ToolResult(True, output=output), status="completed")
        yield AgentEvent("text", text="The operation is complete.")
    async def close(self) -> None:
        pass
class BlockingPermissionAgent:
    def __init__(self, app: BoltpyApp) -> None:
        self.app = app
        self.tool_started = asyncio.Event()
        self.tool_finished = asyncio.Event()
        self.decision_resolved = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_events(self, prompt: str):
        request = PermissionRequest("run_shell", "shell.execute", {"command": "sleep 10"})
        yield AgentEvent("tool_call", name="run_shell", arguments=request.arguments, status="requested")
        yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status="waiting")
        decision = await self.app.permissions.authorize(request)
        self.decision_resolved.set()
        if decision == PermissionDecision.DENY:
            yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status="deny")
            await self.release.wait()
            yield AgentEvent("tool_result", name="run_shell", result=ToolResult(False, error="Permission denied"), status="failed")
        else:
            self.tool_started.set()
            await self.release.wait()
            self.tool_finished.set()
            yield AgentEvent("permission", name="run_shell", arguments=request.arguments, status=decision.value)
            yield AgentEvent("tool_result", name="run_shell", result=ToolResult(True, output="done"), status="completed")
        yield AgentEvent("text", text="The operation is complete.")

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_permission_screen_waits_in_agent_worker_and_allow_once_continues():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = PermissionAgent(app)
        app.agent = fake
        worker = app._ask("run ls -la")
        await pilot.pause()
        assert app.query_one(PermissionPrompt).display
        await pilot.click("#allow-once")
        await worker.wait()
        assert fake.executed
        assert not app.query_one(PermissionPrompt).display

@pytest.mark.asyncio
async def test_permission_screen_deny_does_not_execute_tool():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = PermissionAgent(app)
        app.agent = fake
        worker = app._ask("run ls -la")
        await pilot.pause()
        assert app.query_one(PermissionPrompt).display
        await pilot.click("#deny")
        await worker.wait()
        assert not fake.executed
        assert app.query_one("#prompt").has_focus
        assert not app.query_one(PermissionPrompt).display

@pytest.mark.asyncio
async def test_permission_screen_keyboard_focus_and_escape_denies():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = PermissionAgent(app)
        app.agent = fake
        worker = app._ask("run ls -la")
        await pilot.pause()
        screen = app.query_one(PermissionPrompt)
        assert isinstance(screen, PermissionPrompt)
        assert screen.query_one("#allow-once").has_focus
        await pilot.press("tab")
        assert screen.query_one("#allow-session").has_focus
        await pilot.press("tab")
        assert screen.query_one("#allow-permanent").has_focus
        await pilot.press("tab")
        assert screen.query_one("#deny").has_focus
        await pilot.press("escape")
        await worker.wait()
        assert not fake.executed
        assert app.query_one("#prompt").has_focus
        assert not app.query_one(PermissionPrompt).display

@pytest.mark.asyncio
async def test_permission_screen_enter_and_space_activate_focused_action():
    for key in ("enter", "space"):
        app = BoltpyApp(Settings(api_key="test"))
        async with app.run_test() as pilot:
            fake = PermissionAgent(app)
            app.agent = fake
            worker = app._ask("run ls -la")
            await pilot.pause()
            await pilot.press(key)
            await worker.wait()
            assert fake.executed
            assert not app.query_one(PermissionPrompt).display

@pytest.mark.asyncio
async def test_inline_permission_allow_session_click_resolves_request():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = PermissionAgent(app)
        app.agent = fake
        worker = app._ask("run ls -la")
        await pilot.pause()
        prompt = app.query_one(PermissionPrompt)
        assert prompt.display
        assert str(prompt.query_one("#permission-details").render()) == "$ ls -la"
        await pilot.click("#allow-session")
        await worker.wait()
        assert fake.executed
        assert app.permissions._session_grants == {"shell.execute"}
@pytest.mark.asyncio
async def test_prompt_focus_returns_before_approved_tool_finishes():
    app = BoltpyApp(Settings(api_key="test"))
    async with app.run_test() as pilot:
        fake = BlockingPermissionAgent(app)
        app.agent = fake
        worker = app._ask("run a long command")
        await pilot.pause()
        assert app.query_one(PermissionPrompt).query_one("#allow-once").has_focus
        await pilot.click("#allow-once")
        await fake.tool_started.wait()
        await asyncio.sleep(0)
        prompt = app.query_one("#prompt")
        assert prompt.display
        assert prompt.has_focus
        prompt.text = "next prompt"
        await app._submit_prompt(prompt.text)
        assert app._prompt_queue == ["next prompt"]
        assert not fake.tool_finished.is_set()
        app._prompt_queue.clear()
        app._queued_task_started_at.clear()
        fake.release.set()
        await worker.wait()
