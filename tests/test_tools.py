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
    assert names == ["read_file", "list_dir", "run_shell"]

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
