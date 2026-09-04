"""Behavioral coverage for fresh and explicitly resumed process lifecycles."""
from __future__ import annotations

import pytest

from boltpy.agent.core import Agent
from boltpy.agent.session import SessionStore
from boltpy.config import Settings, load_settings, resolve_resume, resume_from_environment


class CapturingProvider:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, object]]] = []

    async def stream(self, messages):
        self.requests.append(list(messages))
        yield "fresh response"

    async def close(self) -> None:
        pass


def _seed_session(root, content: str = "old conversation") -> bytes:
    store = SessionStore(root)
    store.save([
        {"role": "system", "content": "system"},
        {"role": "user", "content": content},
        {"role": "assistant", "content": "old answer"},
    ])
    return store.path.read_bytes()


@pytest.mark.asyncio
async def test_normal_agent_start_is_fresh_and_preserves_existing_session(tmp_path):
    original = _seed_session(tmp_path)
    provider = CapturingProvider()
    agent = Agent(Settings(workspace=tmp_path), provider=provider)

    assert agent.resumed is False
    assert [message["role"] for message in agent.messages] == ["system"]
    [event async for event in agent.stream_events("new prompt")]
    assert [message["content"] for message in provider.requests[0]] == [agent.messages[0]["content"], "new prompt"]
    assert SessionStore(tmp_path).path.read_bytes() == original


@pytest.mark.asyncio
async def test_explicit_resume_restores_history_for_headless_agent(tmp_path):
    _seed_session(tmp_path)
    provider = CapturingProvider()
    agent = Agent(Settings(workspace=tmp_path, resume=True), provider=provider)

    assert agent.resumed is True
    [event async for event in agent.stream_events("continue")]
    assert [message["content"] for message in provider.requests[0]][-2:] == ["old answer", "continue"]


def test_resume_environment_parser_is_strict(monkeypatch, tmp_path):
    for value in ("1", "true", "TRUE", "yes", "on"):
        assert resume_from_environment(value)
    for value in (None, "", "0", "false", "no", "off", "random"):
        assert not resume_from_environment(value)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOLT_RESUME", "0")
    assert load_settings().resume is False
    monkeypatch.setenv("BOLT_RESUME", "1")
    assert load_settings().resume is True


def test_cli_resume_intent_overrides_environment():
    settings = Settings(resume=True)
    assert resolve_resume(None, settings).resume is True
    assert resolve_resume(False, settings).resume is False
    assert resolve_resume(True, Settings(resume=False)).resume is True
