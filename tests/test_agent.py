import pytest
from boltpy.agent.core import Agent
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
