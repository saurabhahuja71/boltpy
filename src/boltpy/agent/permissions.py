"""Provider-independent permission decisions and scoped persistent grants."""
from __future__ import annotations
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

class PermissionLevel(StrEnum):
    """Risk level used to decide whether a tool may run automatically."""
    SAFE = "safe"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"

class PermissionMode(StrEnum):
    """Whether approval is required for tools that declare a capability."""
    ASK = "ask"
    ALLOW = "allow"
    PLAN = "plan"

class PermissionDecision(StrEnum):
    """Decision returned by a permission handler."""
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_PERMANENT = "allow_permanent"
    DENY = "deny"

@dataclass(frozen=True)
class PermissionRequest:
    """A capability-specific request independent of any UI framework."""
    tool_name: str
    capability: str
    arguments: dict[str, Any]
    level: PermissionLevel = PermissionLevel.CONFIRM

PermissionHandler = Callable[[PermissionRequest], PermissionDecision | Awaitable[PermissionDecision]]

@dataclass
class PermissionStore:
    """Small human-readable TOML store for explicit permanent grants."""
    path: Path = field(default_factory=lambda: Path.home() / ".config" / "boltpy" / "permissions.toml")

    def _read(self) -> dict[str, Any]:
        import tomllib
        if not self.path.is_file():
            return {"commands": {}, "ssh": {}}
        with self.path.open("rb") as stream:
            value = tomllib.load(stream)
        return value if isinstance(value, dict) else {"commands": {}, "ssh": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for section in ("commands", "ssh"):
            entries = data.get(section, {})
            if entries:
                lines.append(f"[{section}]\n")
                lines.extend(f"{json.dumps(str(key))} = true\n" for key in sorted(entries))
                lines.append("\n")
        self.path.write_text("".join(lines), encoding="utf-8")

    def contains(self, section: str, scope: str) -> bool:
        return bool(self._read().get(section, {}).get(scope, False))

    def add(self, section: str, scope: str) -> None:
        data = self._read()
        data.setdefault(section, {})[scope] = True
        self._write(data)

    def remove(self, section: str, scope: str) -> bool:
        data = self._read()
        entries = data.get(section, {})
        if scope not in entries:
            return False
        del entries[scope]
        self._write(data)
        return True

    def entries(self) -> list[tuple[str, str]]:
        data = self._read()
        return [(section, str(scope)) for section in ("commands", "ssh") for scope in data.get(section, {})]

@dataclass
class PermissionManager:
    """Resolve permissions asynchronously and remember explicit grants."""
    mode: PermissionMode = PermissionMode.ASK
    handler: PermissionHandler | None = None
    store: PermissionStore = field(default_factory=PermissionStore)
    _session_grants: set[str] = field(default_factory=set)

    async def authorize(self, request: PermissionRequest) -> PermissionDecision:
        """Return a decision, pausing asynchronously when a handler is present."""
        if not request.capability:
            return PermissionDecision.ALLOW_ONCE
        # Dangerous actions always require a fresh explicit decision, even in
        # allow mode, and are never remembered as session/permanent grants.
        if self.mode == PermissionMode.ALLOW and request.level != PermissionLevel.DANGEROUS:
            return PermissionDecision.ALLOW_ONCE
        if self.mode == PermissionMode.PLAN:
            # Plan mode blocks write/shell actions so the agent must propose a
            # plan instead; read-only tools have no capability and pass above.
            return PermissionDecision.DENY
        if request.capability in self._session_grants:
            return PermissionDecision.ALLOW_SESSION
        section, scope = self._scope(request)
        if self.store.contains(section, scope):
            return PermissionDecision.ALLOW_PERMANENT
        if self.handler is None:
            return PermissionDecision.DENY
        decision = self.handler(request)
        if hasattr(decision, "__await__"):
            decision = await decision
        if request.level == PermissionLevel.DANGEROUS:
            return PermissionDecision.ALLOW_ONCE if decision in {PermissionDecision.ALLOW_SESSION, PermissionDecision.ALLOW_PERMANENT} else decision
        if decision == PermissionDecision.ALLOW_SESSION:
            self._session_grants.add(request.capability)
        elif decision == PermissionDecision.ALLOW_PERMANENT:
            self.store.add(section, scope)
        return decision

    @staticmethod
    def _scope(request: PermissionRequest) -> tuple[str, str]:
        if request.tool_name in {"run_shell", "run_command"}:
            return "commands", str(request.arguments.get("command", ""))
        if request.tool_name == "ssh":
            values = (request.arguments.get("host", ""), request.arguments.get("user", ""), request.arguments.get("port", ""), request.arguments.get("command", ""))
            return "ssh", "|".join(str(value) for value in values)
        return "commands", request.tool_name + ":" + json.dumps(request.arguments, sort_keys=True, separators=(",", ":"))

    def permanent_entries(self) -> list[tuple[str, str]]:
        return self.store.entries()

    def remove_permanent(self, section: str, scope: str) -> bool:
        return self.store.remove(section, scope)

    def clear_session_grants(self) -> None:
        """Forget grants when the application starts a new session."""
        self._session_grants.clear()
