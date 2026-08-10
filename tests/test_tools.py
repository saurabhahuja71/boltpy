import pytest
from boltpy.agent.core import Agent
from boltpy.agent.permissions import PermissionManager, PermissionDecision
from boltpy.agent.providers import ProviderEvent
from boltpy.agent.tools import default_registry, run_shell
from boltpy.config import Settings

class ToolProvider:
    def __init__(self, name="list_dir", arguments="{\"path\": \".\"}"):
        self.calls = []
        self.name = name
        self.arguments = arguments
        self.turn = 0
    async def stream_response(self, messages, tools):
        self.calls.append(messages)
        if self.turn == 0:
            self.turn += 1
            yield ProviderEvent("tool_call", call_id="call-1", name=self.name, arguments=self.arguments)
        else:
            yield ProviderEvent("text", text="done")
    async def close(self):
        pass

@pytest.mark.asyncio
async def test_agent_executes_tool_and_feeds_result_back():
    provider = ToolProvider()
    agent = Agent(Settings(permission_mode="allow"), provider=provider)
    events = [event async for event in agent.stream_events("what is here?")]
    assert [(event.kind, event.name) for event in events] == [("tool_call", "list_dir"), ("tool_result", "list_dir"), ("text", "")]
    assert any(message["role"] == "tool" for message in provider.calls[1])

@pytest.mark.asyncio
async def test_permission_callback_can_deny_tool():
    provider = ToolProvider("run_shell", '{"command": "echo hi"}')
    agent = Agent(Settings(), provider=provider, permissions=PermissionManager(handler=lambda request: PermissionDecision.DENY))
    events = [event async for event in agent.stream_events("what is here?")]
    result = next(event.result for event in events if event.kind == "tool_result")
    assert result.error == "Permission denied"

@pytest.mark.asyncio
async def test_shell_blocks_destructive_command():
    with pytest.raises(PermissionError):
        await run_shell("rm -rf /")

def test_default_registry_has_expected_schemas():
    names = [schema["function"]["name"] for schema in default_registry().schemas()]
    assert names == ["read_file", "list_dir", "run_shell", "ssh", "http_request", "present_options", "add_todo", "complete_todo", "update_todo", "list_todos"]

@pytest.mark.asyncio
async def test_allow_session_grant_is_reused_by_capability():
    requests = []
    async def handler(request):
        requests.append(request)
        return PermissionDecision.ALLOW_SESSION
    manager = PermissionManager(handler=handler)
    request = default_registry().get("run_shell").permission_request({"command": "echo hi"})
    assert request is not None
    assert await manager.authorize(request) == PermissionDecision.ALLOW_SESSION
    assert await manager.authorize(request) == PermissionDecision.ALLOW_SESSION
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_run_shell_returns_structured_stdout_stderr_and_exit_code():
    result = await run_shell("printf out; printf err >&2")
    assert result.success
    assert result.exit_code == 0
    assert result.stdout == "out"
    assert result.stderr == "err"
    failed = await run_shell("printf bad >&2; exit 3")
    assert not failed.success
    assert failed.exit_code == 3
    assert failed.stderr == "bad"

@pytest.mark.asyncio
async def test_run_shell_timeout_returns_without_hanging():
    result = await run_shell("sleep 1", timeout=0.05)
    assert not result.success
    assert result.timed_out
    assert "timed out" in result.error

@pytest.mark.asyncio
async def test_ssh_builds_system_ssh_command(monkeypatch):
    captured = {}
    class FakeProcess:
        returncode = 0
        async def communicate(self): return b"disk", b""
        async def wait(self): return None
    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()
    monkeypatch.setattr("boltpy.agent.tools.asyncio.create_subprocess_exec", fake_exec)
    from boltpy.agent.tools import ssh
    result = await ssh("myserver", "df -h", user="alice", port=2222)
    assert result.success
    assert captured["args"] == ("ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", "2222", "alice@myserver", "df -h")
    assert captured["kwargs"]["stdin"] is not None

@pytest.mark.asyncio
async def test_ssh_failure_and_safety_are_clear(monkeypatch):
    class FailedProcess:
        returncode = 255
        async def communicate(self): return b"", b"Permission denied"
        async def wait(self): return None
    async def fake_exec(*args, **kwargs): return FailedProcess()
    monkeypatch.setattr("boltpy.agent.tools.asyncio.create_subprocess_exec", fake_exec)
    from boltpy.agent.tools import ssh
    result = await ssh("myserver", "df -h")
    assert not result.success
    assert result.error == "Permission denied"
    with pytest.raises(PermissionError):
        await ssh("myserver", "rm -rf /")

@pytest.mark.asyncio
async def test_ssh_safety_rejection_happens_before_permission():
    provider = ToolProvider("ssh", '{"host": "myserver", "command": "rm -rf /"}')
    requests = []
    manager = PermissionManager(handler=lambda request: requests.append(request) or PermissionDecision.ALLOW_ONCE)
    agent = Agent(Settings(), provider=provider, permissions=manager)
    events = [event async for event in agent.stream_events("check server")]
    result = next(event.result for event in events if event.kind == "tool_result")
    assert not result.success
    assert "destructive" in result.error
    assert requests == []
