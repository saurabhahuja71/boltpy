"""Extensible local and remote command tools for Boltpy."""
from __future__ import annotations
import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boltpy.agent.providers import Provider, ProviderCapabilityError
import httpx
from boltpy.agent.permissions import PermissionLevel, PermissionRequest
from boltpy.agent.todos import todo_store

ToolFunction = Callable[..., Any]
OutputHandler = Callable[[str, bool], Any]
ToolValidator = Callable[[dict[str, Any]], None]
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

@dataclass(frozen=True)
class ToolResult:
    """Structured execution result shared by the model and UI."""
    ok: bool
    output: str = ""
    error: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    cancelled: bool = False

    @property
    def success(self) -> bool:
        """Alias useful to callers that prefer a success field."""
        return self.ok

    def as_message(self, limit: int = 12000) -> str:
        """Format structured, bounded detail for a later model turn."""
        def bounded(value: str) -> tuple[str, bool]:
            if len(value) <= limit:
                return value, False
            head = max(1, int(limit * 0.7))
            tail = max(1, limit - head)
            return f"{value[:head]}\n…[truncated; last portion follows]…\n{value[-tail:]}", True

        lines = [f"success: {self.ok}"]
        if self.exit_code is not None: lines.append(f"exit_code: {self.exit_code}")
        if self.duration: lines.append(f"duration: {self.duration:.2f}s")
        if self.timed_out: lines.append("timed_out: true")
        if self.cancelled: lines.append("cancelled: true")
        if self.error: lines.append(f"error: {self.error}")
        if self.stdout:
            stdout, truncated = bounded(self.stdout)
            lines.append(f"stdout{' (truncated)' if truncated else ''}:\n{stdout}")
        if self.stderr:
            stderr, truncated = bounded(self.stderr)
            lines.append(f"stderr{' (truncated)' if truncated else ''}:\n{stderr}")
        if not self.stdout and not self.stderr and self.output: lines.append(self.output)
        return "\n".join(lines)

    def display(self, limit: int = 700) -> str:
        """Create a concise human-facing result without flooding the transcript."""
        text = self.output or self.stdout or self.stderr or self.error or "(no output)"
        if self.stdout and self.stderr: text = f"stdout:\n{self.stdout}\nstderr:\n{self.stderr}"
        if len(text) > limit: text = text[: limit - 1] + "…"
        return text

@dataclass(frozen=True)
class Tool:
    """A named function, provider schema, capability, and safety validator."""
    name: str
    description: str
    parameters: dict[str, Any]
    function: ToolFunction
    capability: str | None = None
    validator: ToolValidator | None = None
    permission_level: PermissionLevel = PermissionLevel.SAFE
    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}
    def permission_request(self, arguments: dict[str, Any]) -> PermissionRequest | None:
        if not self.capability: return None
        level = self.permission_level
        if self.name in {"run_shell", "run_command", "ssh", "ssh_execute"} and any(re.search(pattern, str(arguments.get("command", "")), re.IGNORECASE) for pattern in _DANGEROUS_COMMANDS):
            level = PermissionLevel.DANGEROUS
        return PermissionRequest(self.name, self.capability, arguments, level)
    def validate(self, arguments: dict[str, Any]) -> None:
        if self.validator: self.validator(arguments)

class ToolRegistry:
    """Registry used by both headless and interactive agent execution."""
    def __init__(self, output_handler: OutputHandler | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self.output_handler = output_handler
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools: raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
    def get(self, name: str) -> Tool:
        try: return self._tools[name]
        except KeyError as error: raise ValueError(f"Unknown tool: {name}") from error
    def schemas(self) -> list[dict[str, Any]]: return [tool.schema() for tool in self._tools.values()]
    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate and execute a tool, normalizing failures into results."""
        try:
            tool = self.get(name)
            tool.validate(arguments)
            call_arguments = dict(arguments)
            if self.output_handler is not None and name in {"run_shell", "run_command"}:
                call_arguments["on_output"] = self.output_handler
            result = tool.function(**call_arguments)
            if asyncio.iscoroutine(result): result = await result
            return result if isinstance(result, ToolResult) else ToolResult(ok=True, output=str(result))
        except Exception as error:
            return ToolResult(ok=False, error=str(error))

_DANGEROUS_COMMANDS = (
    r"(^|\s)rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/($|\s)",
    r"(^|\s)rm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(/|\*|\.\.)",
    r"(^|\s)(mkfs|fdisk|shutdown|reboot|poweroff)\b",
    r"(^|\s)dd\s+if=",
    r"(^|\s)find\s+/[^\n]*-delete\b",
    r"(^|\s)chmod\s+(-R\s+)?[0-7]{3,4}\s+/$",
    r":\(\)\s*\{.*:\|:.*\};:",
)

def validate_shell_command(command: str) -> None:
    """Reject empty or obviously catastrophic filesystem commands."""
    if not isinstance(command, str) or not command.strip(): raise ValueError("Shell command cannot be empty")
    if any(re.search(pattern, command, re.IGNORECASE) for pattern in _DANGEROUS_COMMANDS):
        raise PermissionError("Blocked potentially destructive shell command")

def _validate_timeout(value: float) -> None:
    if value <= 0 or value > 300: raise ValueError("timeout must be greater than 0 and no more than 300 seconds")

def read_file(path: str) -> str:
    """Read a UTF-8 text file."""
    try: return Path(path).read_text(encoding="utf-8")
    except OSError as error: raise RuntimeError(f"Could not read {path!r}: {error}") from error

def list_dir(path: str = ".") -> str:
    """List directory entries in stable order."""
    try: entries = sorted(Path(path).iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError as error: raise RuntimeError(f"Could not list {path!r}: {error}") from error
    return "\n".join(f"{item.name}{'/' if item.is_dir() else ''}" for item in entries) or "(empty directory)"

async def _read_output(stream: asyncio.StreamReader | None, chunks: list[bytes], on_output: OutputHandler | None, is_stderr: bool) -> None:
    """Read one subprocess pipe incrementally and publish decoded chunks."""
    if stream is None:
        return
    while data := await stream.read(1024):
        chunks.append(data)
        if on_output is not None:
            value = data.decode("utf-8", errors="replace")
            callback_result = on_output(value, is_stderr)
            if hasattr(callback_result, "__await__"):
                await callback_result

async def _communicate(process: asyncio.subprocess.Process, timeout: float, on_output: OutputHandler | None = None) -> tuple[bytes, bytes, bool]:
    """Collect process output incrementally, terminating on timeout or cancellation."""
    if not hasattr(process, "stdout") or not hasattr(process, "stderr"):
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return stdout or b"", stderr or b"", False
        except asyncio.TimeoutError:
            return b"", b"", True
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    readers = [
        asyncio.create_task(_read_output(process.stdout, stdout_chunks, on_output, False)),
        asyncio.create_task(_read_output(process.stderr, stderr_chunks, on_output, True)),
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*readers), timeout=timeout)
        await process.wait()
        return b"".join(stdout_chunks), b"".join(stderr_chunks), False
    except asyncio.TimeoutError:
        process.terminate()
        try: await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError: process.kill(); await process.wait()
        await asyncio.gather(*readers, return_exceptions=True)
        return b"".join(stdout_chunks), b"".join(stderr_chunks), True
    except asyncio.CancelledError:
        process.terminate()
        try: await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError: process.kill(); await process.wait()
        for reader in readers: reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        raise


async def run_shell(command: str, timeout: float = 30, on_output: OutputHandler | None = None, cwd: str | os.PathLike[str] | None = None) -> ToolResult:
    """Run a bounded shell command while publishing output incrementally."""
    validate_shell_command(command)
    _validate_timeout(timeout)
    started = time.perf_counter()
    process = await asyncio.create_subprocess_shell(command, cwd=str(cwd) if cwd is not None else None, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr, timed_out = await _communicate(process, timeout, on_output)
    duration = time.perf_counter() - started
    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if timed_out:
        return ToolResult(False, error=f"Command timed out after {timeout:g} seconds", exit_code=process.returncode, stdout=out, stderr=err, duration=duration, timed_out=True)
    return ToolResult(process.returncode == 0, output=out, exit_code=process.returncode, stdout=out, stderr=err, duration=duration, error=err if process.returncode else "")

def _validate_ssh(arguments: dict[str, Any]) -> None:
    host = arguments.get("host")
    if not isinstance(host, str) or not host.strip(): raise ValueError("SSH host cannot be empty")
    validate_shell_command(arguments.get("command", ""))
    _validate_timeout(float(arguments.get("timeout", 30)))

def _ssh_target(host: str, user: str | None) -> str:
    if user and "@" in host: raise ValueError("Specify SSH user separately or as user@host, not both")
    return f"{user}@{host}" if user else host

def _proxy_jump_for_host(host: str) -> str | None:
    """Resolve a local SSH alias to its ProxyJump host."""
    try:
        bashrc = (Path.home() / ".bashrc").read_text(encoding="utf-8")
    except OSError:
        return None
    pattern = re.compile(
        r"^\s*alias\s+\w+=['\"]ssh\s+-J\s+(\S+)\s+[^@'\"]+@"
        + re.escape(host)
        + r"['\"]\s*$",
        re.MULTILINE,
    )
    match = pattern.search(bashrc)
    return match.group(1) if match else None

async def ssh(host: str, command: str, user: str | None = None, port: int | None = None, timeout: float = 30) -> ToolResult:
    """Run a non-interactive command using the system SSH client and SSH config."""
    _validate_ssh({"host": host, "command": command, "timeout": timeout}); started = time.perf_counter()
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    ssh_config = os.getenv("SSH_CONFIG_PATH") or str(Path.home() / ".ssh/config")
    if Path(ssh_config).is_file(): args += ["-F", ssh_config]
    proxy_jump = _proxy_jump_for_host(host)
    if proxy_jump:
        args += ["-J", proxy_jump]
    if port is not None:
        if not 1 <= int(port) <= 65535: raise ValueError("SSH port must be between 1 and 65535")
        args += ["-p", str(int(port))]
    args += [_ssh_target(host, user), command]
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr, timed_out = await _communicate(process, timeout)
    duration = time.perf_counter() - started
    out = stdout.decode("utf-8", errors="replace").strip(); err = stderr.decode("utf-8", errors="replace").strip()
    if timed_out: return ToolResult(False, error=f"SSH command timed out after {timeout:g} seconds", exit_code=process.returncode, stdout=out, stderr=err, duration=duration, timed_out=True)
    error = err if process.returncode else ""
    if process.returncode and not error: error = f"ssh exited with status {process.returncode}"
    return ToolResult(process.returncode == 0, output=out, exit_code=process.returncode, stdout=out, stderr=err, duration=duration, error=error)

def _validate_http(arguments: dict[str, Any]) -> None:
    url = arguments.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("url must be a valid http(s) URL")
    _validate_timeout(float(arguments.get("timeout", 30)))

async def http_request(method: str = "GET", url: str = "", headers: dict[str, str] | None = None,
                       body: Any = None, timeout: float = 30) -> ToolResult:
    """Perform an HTTP(S) request with a bounded timeout and clear errors."""
    _validate_http({"url": url, "timeout": timeout})
    method = (method or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        raise ValueError(f"Unsupported HTTP method: {method}")
    if headers is not None and not isinstance(headers, dict):
        raise ValueError("headers must be an object of key/value pairs")
    request_kwargs: dict[str, Any] = {"headers": headers}
    if isinstance(body, str):
        request_kwargs["content"] = body
    elif body is not None:
        request_kwargs["json"] = body
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(method, url, **request_kwargs)
    except httpx.TimeoutException:
        return ToolResult(False, error=f"HTTP request timed out after {timeout:g} seconds", timed_out=True)
    except httpx.RequestError as error:
        return ToolResult(False, error=f"HTTP request failed: {error}")
    duration = time.perf_counter() - started
    text = response.text
    if len(text) > 20000:
        text = text[:19997] + "\n…[truncated]"
    ok = 200 <= response.status_code < 400
    return ToolResult(ok, output=f"{response.status_code} {method} {url}\n\n{text}",
                      error="" if ok else f"HTTP {response.status_code}",
                      exit_code=response.status_code, duration=duration)

def add_todo(description: str) -> str:
    """Add a todo item."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Todo description cannot be empty")
    todo = todo_store.add(description)
    return json.dumps({"id": todo.id, "content": todo.description})

def complete_todo(todo_id: str) -> str:
    """Mark a todo item as completed."""
    if not todo_store.complete(str(todo_id)):
        raise ValueError(f"No todo with id {todo_id!r}")
    return f"completed todo {todo_id}"

def update_todo(todo_id: str, description: str) -> str:
    """Update a todo item description."""
    if not todo_store.update(str(todo_id), description):
        raise ValueError(f"No todo with id {todo_id!r} or empty description")
    return f"updated todo {todo_id}"

def list_todos() -> str:
    """List the current todo items."""
    return todo_store.summary()

def _present_options_placeholder(title: str, options: list[str], allow_custom: bool = True) -> ToolResult:
    """Fallback used when no interactive options handler is wired up."""
    return ToolResult(ok=False, error="present_options requires an interactive UI; not available here")

async def analyze_image(path: str, prompt: str, workspace: Any, provider: Provider, vision_enabled: bool | None) -> ToolResult:
    """Analyze a bounded workspace image through the configured provider."""
    try:
        target = workspace.path(path)
    except (PermissionError, ValueError) as error:
        return ToolResult(False, error=(
            f"Image path is outside the permitted workspace: {error}. "
            "Place the image inside the workspace or start Bolt with an appropriate workspace."
        ))
    if not target.exists():
        return ToolResult(False, error=f"Image file does not exist: {path}")
    if not target.is_file():
        return ToolResult(False, error=f"Image path is not a regular file: {path}")
    if target.suffix.casefold() not in _SUPPORTED_IMAGE_SUFFIXES:
        return ToolResult(False, error="Unsupported image type; supported formats are PNG, JPEG/JPG, and WEBP")
    try:
        size = target.stat().st_size
    except OSError as error:
        return ToolResult(False, error=f"Could not inspect image metadata: {error}")
    if size > _MAX_IMAGE_BYTES:
        return ToolResult(False, error=f"Image is too large ({size} bytes); maximum supported size is {_MAX_IMAGE_BYTES} bytes")
    if vision_enabled is not True:
        state = "unknown" if vision_enabled is None else "disabled"
        return ToolResult(False, error=(
            f"Image analysis is {state} for the current provider/model configuration. "
            "The image was not inspected; set vision_enabled=true for an explicitly authorized attempt."
        ))
    try:
        result = await provider.analyze_image(target, prompt)
    except ProviderCapabilityError as error:
        return ToolResult(False, error=f"Image analysis unavailable for the configured provider/model: {error}")
    except Exception as error:
        return ToolResult(False, error=f"Image analysis provider request failed: {error}")
    return ToolResult(True, output=result)


def default_registry(root: str | os.PathLike[str] = ".", provider: Provider | None = None, vision_enabled: bool | None = None,
                     vision_state: Callable[[], bool | None] | None = None) -> ToolRegistry:
    """Build the standard registry; callers may register more tools."""
    registry = ToolRegistry()
    from boltpy.agent.coding import Workspace, coding_registry
    workspace = Workspace(root)
    coding_registry(registry, workspace)
    if provider is not None:
        registry.register(Tool(
            "analyze_image",
            "Analyze a supported workspace image with the configured vision-capable provider/model.",
            {"type": "object", "properties": {"path": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["path", "prompt"]},
            lambda path, prompt: analyze_image(
                path, prompt, workspace, provider,
                vision_state() if vision_state is not None else vision_enabled,
            ),
        ))
    shell_schema = {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "number", "default": 30}}, "required": ["command"]}
    shell_validator = lambda args: (validate_shell_command(args.get("command", "")), _validate_timeout(float(args.get("timeout", 30))))
    workspace_root = Workspace(root).root
    run_command = lambda command, timeout=30, on_output=None: run_shell(command, timeout, on_output, cwd=workspace_root)
    registry.register(Tool("run_command", "Run a local shell command in the workspace when permitted.", shell_schema, run_command, capability="shell.execute", validator=shell_validator, permission_level=PermissionLevel.CONFIRM))
    registry.register(Tool("run_shell", "Compatibility alias for run_command.", shell_schema, run_command, capability="shell.execute", validator=shell_validator, permission_level=PermissionLevel.CONFIRM))
    ssh_schema = {"type": "object", "properties": {"host": {"type": "string", "description": "SSH config alias, for example podman8 or podman9"}, "command": {"type": "string"}, "user": {"type": "string"}, "port": {"type": "integer"}, "timeout": {"type": "number", "default": 30}}, "required": ["host", "command"]}
    # Keep the old name for compatibility, but expose the benchmark contract
    # explicitly.  A model cannot call ssh_execute if it is not in the schema.
    registry.register(Tool("ssh_execute", "Execute a command remotely through SSH. Use this for every remote command; do not use run_shell.", ssh_schema, ssh, capability="ssh.execute", validator=_validate_ssh, permission_level=PermissionLevel.CONFIRM))
    registry.register(Tool("ssh", "Compatibility alias for ssh_execute.", ssh_schema, ssh, capability="ssh.execute", validator=_validate_ssh, permission_level=PermissionLevel.CONFIRM))
    registry.register(Tool("http_request", "Perform an HTTP(S) request and return the response body. Useful for web APIs such as GitLab.", {"type": "object", "properties": {"method": {"type": "string", "default": "GET"}, "url": {"type": "string"}, "headers": {"type": "object"}, "body": {"type": ["string", "object"]}, "timeout": {"type": "number", "default": 30}}, "required": ["url"]}, http_request, validator=_validate_http))
    registry.register(Tool("present_options", "Present a short numbered menu of choices to the user and return the selected choice.", {"type": "object", "properties": {"title": {"type": "string", "default": "Choose an option"}, "options": {"type": "array", "items": {"type": "string"}}, "allow_custom": {"type": "boolean", "default": True}}, "required": ["options"]}, _present_options_placeholder))
    registry.register(Tool("add_todo", "Add a todo item to the shared list.", {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}, add_todo))
    registry.register(Tool("complete_todo", "Mark a todo item as completed.", {"type": "object", "properties": {"todo_id": {"type": "string"}}, "required": ["todo_id"]}, complete_todo))
    registry.register(Tool("update_todo", "Change the description of a todo item.", {"type": "object", "properties": {"todo_id": {"type": "string"}, "description": {"type": "string"}}, "required": ["todo_id", "description"]}, update_todo))
    registry.register(Tool("list_todos", "List the current todo items.", {"type": "object", "properties": {}}, list_todos))
    return registry

def parse_arguments(raw: str) -> dict[str, Any]:
    """Decode model-supplied function arguments."""
    try: value = json.loads(raw or "{}")
    except json.JSONDecodeError as error: raise ValueError(f"Invalid tool arguments: {error}") from error
    if not isinstance(value, dict): raise ValueError("Tool arguments must be a JSON object")
    return value
