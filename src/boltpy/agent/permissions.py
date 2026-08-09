"""Provider-independent permission decisions for agent tools."""
from __future__ import annotations
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

class PermissionMode(StrEnum):
    """Whether approval is required for tools that declare a capability."""
    ASK = "ask"
    ALLOW = "allow"

class PermissionDecision(StrEnum):
    """Decision returned by a permission handler."""
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"

@dataclass(frozen=True)
class PermissionRequest:
    """A capability-specific request independent of any UI framework."""
    tool_name: str
    capability: str
    arguments: dict[str, Any]

PermissionHandler = Callable[[PermissionRequest], PermissionDecision | Awaitable[PermissionDecision]]

@dataclass
class PermissionManager:
    """Resolve tool permissions and remember only explicit session grants."""
    mode: PermissionMode = PermissionMode.ASK
    handler: PermissionHandler | None = None
    _session_grants: set[str] = field(default_factory=set)

    async def authorize(self, request: PermissionRequest) -> PermissionDecision:
        """Return a decision, pausing asynchronously when a handler is present."""
        if not request.capability or self.mode == PermissionMode.ALLOW:
            return PermissionDecision.ALLOW_ONCE
        if request.capability in self._session_grants:
            return PermissionDecision.ALLOW_SESSION
        if self.handler is None:
            return PermissionDecision.DENY
        decision = self.handler(request)
        if hasattr(decision, "__await__"):
            decision = await decision
        if decision == PermissionDecision.ALLOW_SESSION:
            self._session_grants.add(request.capability)
        return decision

    def clear_session_grants(self) -> None:
        """Forget grants when the application starts a new session."""
        self._session_grants.clear()
