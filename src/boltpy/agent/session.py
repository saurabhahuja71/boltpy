"""Small JSON session store for resumable Bolt conversations."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

class SessionStore:
    def __init__(self, root: Path) -> None:
        self.directory = root / ".bolt" / "sessions"
        self.path = self.directory / "latest.json"
    def save(self, messages: list[dict[str, Any]], task_state: dict[str, Any] | None = None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload={"saved_at": time.time(), "messages": messages, "task_state": task_state}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    def load(self) -> list[dict[str, Any]]:
        try: payload=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError): return []
        messages=payload.get("messages", [])
        return messages if isinstance(messages, list) else []

    def load_task_state(self) -> dict[str, Any] | None:
        try: payload=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError): return None
        value = payload.get("task_state")
        return value if isinstance(value, dict) else None
