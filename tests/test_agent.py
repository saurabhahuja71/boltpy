import pytest
from boltpy.agent.core import Agent
from boltpy.agent.providers import ProviderEvent
from boltpy.config import Settings
class FakeProvider:
    def __init__(self): self.calls = []
    async def stream(self, messages):
        self.calls.append(list(messages))
        yield "hello"
        yield " world"
    async def close(self): pass
@pytest.mark.asyncio
async def test_agent_streams_and_keeps_history():
    provider = FakeProvider()
    agent = Agent(Settings(), provider=provider)
    tokens = [token async for token in agent.stream("hi")]
    assert "".join(tokens) == "hello world"
    assert agent.messages[-1] == {"role": "assistant", "content": "hello world"}


class WorkflowProvider:
    def __init__(self):
        self.turn = 0

    async def stream_response(self, messages, tools):
        calls = [
            ("search_files", '{"query":"serviceType"}'),
            ("read_file", '{"path":"config.yaml"}'),
            ("edit_file", '{"path":"config.yaml","old_text":"serviceType: ClusterIP","new_text":"serviceType: NodePort"}'),
            ("run_command", '{"command":"grep -q NodePort config.yaml"}'),
            ("git_diff", '{}'),
        ]
        if self.turn < len(calls):
            name, arguments = calls[self.turn]
            self.turn += 1
            yield ProviderEvent("tool_call", call_id=f"call-{self.turn}", name=name, arguments=arguments)
        else:
            yield ProviderEvent("text", text="Updated config.yaml and validation passed.")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_agent_real_search_edit_validate_and_diff_workflow(tmp_path):
    import subprocess
    (tmp_path / "config.yaml").write_text("serviceType: ClusterIP\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "bolt@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Bolt Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "config.yaml"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=tmp_path, check=True)
    agent = Agent(Settings(workspace=tmp_path, permission_mode="allow"), provider=WorkflowProvider())
    events = [event async for event in agent.stream_events("Find the service type, update it, validate it, and show the diff.")]
    results = [event for event in events if event.kind == "tool_result"]
    assert [event.name for event in results] == ["search_files", "read_file", "edit_file", "run_command", "git_diff"]
    assert all(event.result and event.result.success for event in results)
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "serviceType: NodePort\n"
    assert "+serviceType: NodePort" in results[-1].result.output
