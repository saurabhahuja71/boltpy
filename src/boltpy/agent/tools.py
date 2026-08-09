"""Extensible, provider-independent local tools for Boltpy."""
from __future__ import annotations
import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from boltpy.agent.permissions import PermissionRequest

ToolFunction = Callable[..., str | Awaitable[str]]

@dataclass(frozen=True)
class ToolResult:
    """Structured result passed to the model and UI."""
    ok: bool
    output: str = ""
    error: str = ""
    def as_message(self) -> str:
        return self.output if self.ok else f"Tool error: {self.error}"

@dataclass(frozen=True)
class Tool:
    """A named function, model schema, and optional permission capability."""
    name: str
    description: str
    parameters: dict[str, Any]
    function: ToolFunction
    capability: str | None = None
    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}
    def permission_request(self, arguments: dict[str, Any]) -> PermissionRequest | None:
        if not self.capability:
            return None
        return PermissionRequest(self.name, self.capability, arguments)

class ToolRegistry:
    """Registry used by both the headless and interactive agent."""
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown tool: {name}") from error
    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]
    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a registered function and normalize all expected failures."""
        try:
            result = self.get(name).function(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return ToolResult(ok=True, output=str(result))
        except Exception as error:
            return ToolResult(ok=False, error=str(error))

_DANGEROUS_COMMANDS = (
    r"(^|\s)rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/($|\s)", r"(^|\s)rm\s+-rf\s+(/|\*|\.\.)",
    r"(^|\s)(mkfs|fdisk|shutdown|reboot|poweroff)\b", r"(^|\s)dd\s+if=", r":\(\)\s*\{.*:\|:.*\};:",
)
def _safe_shell_command(command: str) -> None:
    if not command.strip(): raise ValueError("Shell command cannot be empty")
    if any(re.search(pattern, command, re.IGNORECASE) for pattern in _DANGEROUS_COMMANDS):
        raise PermissionError("Blocked potentially destructive shell command")

def read_file(path: str) -> str:
    """Read a UTF-8 text file."""
    try: return Path(path).read_text(encoding="utf-8")
    except OSError as error: raise RuntimeError(f"Could not read {path!r}: {error}") from error

def list_dir(path: str = ".") -> str:
    """List directory entries in stable order."""
    try: entries = sorted(Path(path).iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError as error: raise RuntimeError(f"Could not list {path!r}: {error}") from error
    return "\n".join(f"{item.name}{'/' if item.is_dir() else ''}" for item in entries) or "(empty directory)"

async def run_shell(command: str) -> str:
    """Run a shell command; authorization is handled by PermissionManager."""
    _safe_shell_command(command)
    process = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try: output, _ = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill(); await process.wait(); raise RuntimeError("Shell command timed out after 30 seconds")
    text = output.decode("utf-8", errors="replace").strip()
    if process.returncode: raise RuntimeError(f"Command exited with status {process.returncode}:\n{text}")
    return text or "(command completed with no output)"

def default_registry() -> ToolRegistry:
    """Build the standard registry; callers may register more tools."""
    registry = ToolRegistry()
    registry.register(Tool("read_file", "Read a UTF-8 text file.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, read_file))
    registry.register(Tool("list_dir", "List files and directories.", {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}, list_dir))
    registry.register(Tool("run_shell", "Run a shell command when permitted.", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, run_shell, capability="shell.execute"))
    return registry

def parse_arguments(raw: str) -> dict[str, Any]:
    """Decode model-supplied function arguments."""
    try: value = json.loads(raw or "{}")
    except json.JSONDecodeError as error: raise ValueError(f"Invalid tool arguments: {error}") from error
    if not isinstance(value, dict): raise ValueError("Tool arguments must be a JSON object")
    return value
