from __future__ import annotations

import pytest

from boltpy.agent.core import Agent
from boltpy.agent.providers import ProviderEvent
from boltpy.agent.text import normalize_response_text
from boltpy.config import Settings
from boltpy.tui.app import BoltpyApp


def test_normalize_response_text_collapses_only_excessive_prose_blanks():
    text = "Paragraph one.\n\n\nParagraph two.\n\nParagraph three."
    assert normalize_response_text(text) == "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    assert normalize_response_text("Paragraph one.\n\nParagraph two.") == "Paragraph one.\n\nParagraph two."


def test_normalize_response_text_compacts_real_fastapi_unfenced_code():
    text = (
        "# main.py\n\n"
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get(\"/\")\n\n"
        "def read_root():\n"
        "return {\"message\": \"Hello\"}"
    )
    expected = (
        "# main.py\n\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.get(\"/\")\n"
        "def read_root():\n"
        "return {\"message\": \"Hello\"}"
    )
    assert normalize_response_text(text) == expected


def test_canonical_prompt_requests_fenced_compact_code():
    from boltpy.agent.core import Agent

    prompt = Agent(Settings(api_key="test")).messages[0]["content"]
    assert "multi-line source code in fenced Markdown blocks" in prompt
    assert "```python" in prompt
    assert "do not insert a blank line between every statement" in prompt


@pytest.mark.parametrize("language", ["python", "bash", "json", ""])
def test_normalize_response_text_preserves_fenced_code(language):
    opening = f"```{language}\n" if language else "```\n"
    code = 'def hello():\n\n\n    return "hello"\n' if language == "python" else '{\n  "enabled": true\n}\n'
    text = f"Before.\n\n\n{opening}{code}```\n\n\nAfter."
    expected = f"Before.\n\n{opening}{code}```\n\nAfter."
    assert normalize_response_text(text) == expected


def test_normalize_response_text_handles_multiple_blocks_indentation_and_idempotence():
    text = (
        "Intro.\n\n\n"
        "```bash\n  printf '%s\\n' ready\n```\n\n\n"
        "Middle.\n\n\n"
        "~~~go\nfunc main() {\n\n\n    println(\"ok\")\n}\n~~~\n\n\n"
        "End."
    )
    normalized = normalize_response_text(text)
    assert normalized == (
        "Intro.\n\n"
        "```bash\n  printf '%s\\n' ready\n```\n\n"
        "Middle.\n\n"
        "~~~go\nfunc main() {\n\n\n    println(\"ok\")\n}\n~~~\n\n"
        "End."
    )
    assert normalize_response_text(normalized) == normalized


class ChunkedResponseProvider:
    async def stream_response(self, messages, tools):
        for chunk in (
            "Paragraph one.\n\n",
            "\nParagraph two.\n\n```python\ndef hello():\n\n",
            "\n    return \"hello\"\n```",
        ):
            yield ProviderEvent(kind="text", text=chunk)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_agent_history_and_copy_use_complete_normalized_response():
    settings = Settings(api_key="test")
    agent = Agent(settings, provider=ChunkedResponseProvider())
    [event async for event in agent.stream_events("reproduce")]
    expected = "Paragraph one.\n\nParagraph two.\n\n```python\ndef hello():\n\n\n    return \"hello\"\n```"
    assert agent.messages[-1]["content"] == expected

    app = BoltpyApp(settings)
    async with app.run_test():
        app.agent = agent
        copied: list[str] = []
        app.copy_to_clipboard = copied.append
        await app._submit_prompt("/copy")
        assert copied == [expected]
