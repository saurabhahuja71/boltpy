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
    assert names == ["read_file", "list_dir", "list_directory", "write_file", "create_file", "edit_file", "find_files", "search_files", "git_status", "git_diff", "git_log", "run_command", "run_shell", "ssh_execute", "ssh", "http_request", "present_options", "add_todo", "complete_todo", "update_todo", "list_todos"]

@pytest.mark.asyncio
async def test_allow_session_grant_is_reused_by_capability():
    requests = []
    async def handler(request):
        requests.append(request)
        return PermissionDecision.ALLOW_SESSION
    manager = PermissionManager(handler=handler)
    request = default_registry().get("run_command").permission_request({"command": "echo hi"})
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


def test_workspace_tools_are_bounded_and_safe(tmp_path):
    from boltpy.agent.coding import Workspace, edit_file, read_file, search_files
    workspace = Workspace(tmp_path)
    target = tmp_path / "config.yaml"
    target.write_text("serviceType: ClusterIP\n" + "padding: x\n" * 250, encoding="utf-8")
    result = read_file("config.yaml", workspace)
    assert "Lines 1-200 of 251" in result and "truncated" in result
    assert "config.yaml:1:serviceType: ClusterIP" in search_files("ClusterIP", ".", workspace)
    assert "one replacement" in edit_file("config.yaml", "serviceType: ClusterIP", "serviceType: NodePort", workspace)
    with pytest.raises(PermissionError): read_file("../outside", workspace)


def test_tool_result_bounds_large_model_context():
    from boltpy.agent.tools import ToolResult
    result = ToolResult(ok=True, stdout="first\n" + "x" * 20000 + "\nlast")
    message = result.as_message(limit=1000)
    assert len(message) < 1300
    assert "first" in message and "last" in message and "truncated" in message


@pytest.mark.asyncio
async def test_run_command_uses_registry_workspace(tmp_path):
    result = await default_registry(tmp_path).execute("run_command", {"command": "pwd"})
    assert result.success
    assert str(tmp_path) in result.stdout
