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


class TodoWorkflowProvider:
    def __init__(self):
        self.turn = 0
        self.seen_id = None

    async def stream_response(self, messages, tools):
        if self.turn == 0:
            self.turn += 1
            yield ProviderEvent("tool_call", call_id="add", name="add_todo", arguments='{"description":"inspect config"}')
        elif self.turn == 1:
            self.turn += 1
            payload = messages[-1]["content"].split("\n", 1)[1]
            import json
            self.seen_id = json.loads(payload)["id"]
            yield ProviderEvent("tool_call", call_id="complete", name="complete_todo", arguments=json.dumps({"todo_id": self.seen_id}))
        else:
            yield ProviderEvent("text", text="Todo completed.")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_agent_uses_returned_todo_id():
    from boltpy.agent.todos import todo_store
    todo_store.clear()
    provider = TodoWorkflowProvider()
    agent = Agent(Settings(), provider=provider)
    events = [event async for event in agent.stream_events("track this task")]
    results = [event for event in events if event.kind == "tool_result"]
    assert [event.name for event in results] == ["add_todo", "complete_todo"]
    assert all(event.result and event.result.success for event in results)
    assert provider.seen_id and provider.seen_id.startswith("todo_") and provider.seen_id != "todo_1"
    assert todo_store.get(provider.seen_id).completed
    todo_store.clear()


class RepeatingFailureProvider:
    def __init__(self):
        self.calls = 0

    async def stream_response(self, messages, tools):
        self.calls += 1
        yield ProviderEvent("tool_call", call_id=f"call-{self.calls}", name="read_file", arguments='{"path":"missing.txt"}')

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_repeated_identical_tool_failure_blocks_without_looping():
    provider = RepeatingFailureProvider()
    agent = Agent(Settings(), provider=provider, emit_lifecycle=True)
    events = [event async for event in agent.stream_events("inspect the missing file")]
    assert provider.calls == 2
    assert any(event.kind == "lifecycle" and event.status == "blocked" for event in events)
    assert agent.task_state is not None
    assert agent.task_state.validation_status == "blocked"
    assert agent.task_state.failure


@pytest.mark.asyncio
async def test_lifecycle_events_are_opt_in_for_compatibility():
    provider = FakeProvider()
    agent = Agent(Settings(), provider=provider)
    events = [event async for event in agent.stream_events("hi")]
    assert all(event.kind != "lifecycle" for event in events)


@pytest.mark.asyncio
async def test_task_state_records_successful_validation(tmp_path):
    class ValidationProvider:
        async def stream_response(self, messages, tools):
            if sum(message.get("role") == "tool" for message in messages) == 0:
                yield ProviderEvent("tool_call", call_id="check", name="run_command", arguments='{"command":"python -m compileall -q ."}')
            else:
                yield ProviderEvent("text", text="validated")

        async def close(self):
            pass

    agent = Agent(Settings(workspace=tmp_path, permission_mode="allow"), provider=ValidationProvider())
    [event async for event in agent.stream_events("validate the workspace")]
    assert agent.task_state is not None
    assert agent.task_state.validation_status == "passed"
    assert "run_command completed" in agent.task_state.completed_steps


@pytest.mark.asyncio
async def test_targeted_validation_is_partial_for_broad_task():
    class TargetedProvider:
        async def stream_response(self, messages, tools):
            if sum(message.get("role") == "tool" for message in messages) == 0:
                yield ProviderEvent("tool_call", call_id="check", name="run_command", arguments='{"command":"pytest tests/test_login.py"}')
            else:
                yield ProviderEvent("text", text="The targeted test passed.")

        async def close(self):
            pass

    from boltpy.agent.permissions import PermissionLevel
    from boltpy.agent.tools import Tool, ToolRegistry, ToolResult
    registry = ToolRegistry()
    registry.register(Tool("run_command", "test", {"type": "object"}, lambda **kwargs: ToolResult(True, stdout="1 passed"), capability="shell.execute", permission_level=PermissionLevel.CONFIRM))
    agent = Agent(Settings(permission_mode="allow"), provider=TargetedProvider(), registry=registry)
    [event async for event in agent.stream_events("Fix all authentication tests.")]
    assert agent.task_state is not None
    assert agent.task_state.validation_scope == "targeted"
    assert agent.task_state.required_validation_scope == "project/full"
    assert agent.task_state.completion_status == "partially_verified"


@pytest.mark.asyncio
async def test_successful_non_validation_command_does_not_verify_task(tmp_path):
    class CommandProvider:
        async def stream_response(self, messages, tools):
            if sum(message.get("role") == "tool" for message in messages) == 0:
                yield ProviderEvent("tool_call", call_id="command", name="run_command", arguments='{"command":"printf changed"}')
            else:
                yield ProviderEvent("text", text="The change was applied.")

        async def close(self):
            pass

    agent = Agent(Settings(workspace=tmp_path, permission_mode="allow"), provider=CommandProvider())
    [event async for event in agent.stream_events("Fix the login implementation.")]
    assert agent.task_state is not None
    assert agent.task_state.validation_attempted is False
    assert agent.task_state.validation_status == "not_applicable"
    assert agent.task_state.completion_status == "completed"
