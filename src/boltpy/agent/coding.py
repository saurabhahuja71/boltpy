"""Workspace-scoped coding and Git tools for Bolt."""
from __future__ import annotations
import asyncio
import fnmatch
import os
import shutil
import subprocess
from pathlib import Path
from boltpy.agent.tools import Tool, ToolRegistry, ToolResult
from boltpy.agent.permissions import PermissionLevel

_MAX_RESULTS = 200
_IGNORED = {".git", ".venv", "node_modules", "__pycache__", ".bolt"}

class Workspace:
    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).expanduser().resolve()

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("workspace path cannot be empty")
        raw = Path(value).expanduser()
        candidate = (self.root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError(f"Path escapes workspace: {value}")
        return candidate

    def rel(self, path: Path) -> str:
        return "." if path == self.root else str(path.relative_to(self.root))

def _text(path: Path) -> str:
    try: return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error: raise ValueError(f"File is not UTF-8 text: {path}") from error

def read_file(path: str, workspace: Workspace, line_start: int = 1, line_end: int | None = None) -> str:
    target = workspace.path(path)
    if not target.is_file(): raise FileNotFoundError(path)
    if line_start < 1 or (line_end is not None and line_end < line_start): raise ValueError("invalid line range")
    lines = _text(target).splitlines()
    requested_end = line_end or min(len(lines), line_start + 199)
    requested_end = min(requested_end, line_start + 199)
    selected = lines[line_start - 1:requested_end]
    actual_end = line_start + len(selected) - 1
    truncated = actual_end < len(lines)
    header = f"{workspace.rel(target)}\nLines {line_start}-{actual_end} of {len(lines)}"
    if truncated: header += " (truncated; request a later range for more)"
    return header + "\n\n" + "\n".join(selected)

def list_directory(path: str, workspace: Workspace, limit: int = 200) -> str:
    target = workspace.path(path)
    if not target.is_dir(): raise NotADirectoryError(path)
    if not 1 <= limit <= 1000: raise ValueError("limit must be between 1 and 1000")
    entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    shown = entries[:limit]
    output = "\n".join(f"{item.name}{'/' if item.is_dir() else ''}" for item in shown) or "(empty directory)"
    return output + (f"\n(listed {len(shown)} of {len(entries)} entries)" if len(entries) > limit else "")

def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.bolt-tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        if target.exists(): shutil.copymode(target, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

def write_file(path: str, content: str, workspace: Workspace) -> str:
    target = workspace.path(path)
    _atomic_write(target, content)
    return f"Wrote {workspace.rel(target)} ({len(content)} bytes)"

def create_file(path: str, content: str, workspace: Workspace) -> str:
    target = workspace.path(path)
    if target.exists(): raise FileExistsError(path)
    return write_file(path, content, workspace)

def edit_file(path: str, old_text: str, new_text: str, workspace: Workspace) -> str:
    target = workspace.path(path)
    if not target.is_file(): raise FileNotFoundError(path)
    current = _text(target); count = current.count(old_text)
    if count == 0: raise ValueError("old_text was not found; file was not changed")
    if count > 1: raise ValueError("old_text matched multiple locations; provide a larger unique block")
    _atomic_write(target, current.replace(old_text, new_text, 1))
    return f"Edited {workspace.rel(target)} (one replacement applied)"

def _excluded(path: Path, workspace: Workspace) -> bool:
    return any(part in _IGNORED for part in path.relative_to(workspace.root).parts)

def find_files(pattern: str, workspace: Workspace, limit: int = _MAX_RESULTS) -> str:
    if not pattern.strip(): raise ValueError("pattern cannot be empty")
    matches = [workspace.rel(path) for path in workspace.root.rglob("*") if path.is_file() and not _excluded(path, workspace) and fnmatch.fnmatch(path.name, pattern)]
    matches.sort()
    shown = matches[:limit]
    if not shown:
        return "(no files found)"
    result = "\n".join(shown)
    return result + (f"\n(results limited to {limit} of {len(matches)})" if len(matches) > limit else "")

def search_files(query: str, path: str, workspace: Workspace, limit: int = _MAX_RESULTS) -> str:
    if not query.strip(): raise ValueError("query cannot be empty")
    base = workspace.path(path)
    if shutil.which("rg"):
        relative_base = workspace.rel(base)
        command = ["rg", "--no-heading", "--line-number", "--color", "never", "--hidden", "--glob", "!.git", "--glob", "!.venv", "--glob", "!node_modules", query, relative_base]
        completed = subprocess.run(command, cwd=workspace.root, capture_output=True, text=True, timeout=10, check=False)
        if completed.returncode not in (0, 1): raise RuntimeError(completed.stderr.strip() or "ripgrep search failed")
        lines = completed.stdout.splitlines(); shown = lines[:limit]
        result = "\n".join(shown) or "(no matches)"
        return result + (f"\n(results limited to {limit})" if len(lines) > limit else "")
    results=[]
    files = [base] if base.is_file() else (p for p in base.rglob("*") if p.is_file() and not _excluded(p, workspace))
    for file in files:
        try: content = _text(file).splitlines()
        except (OSError, ValueError): continue
        for number, line in enumerate(content, 1):
            if query.casefold() in line.casefold(): results.append(f"{workspace.rel(file)}:{number}:{line.strip()}")
            if len(results) >= limit: return "\n".join(results) + f"\n(results limited to {limit})"
    return "\n".join(results) or "(no matches)"

async def _git(args: list[str], workspace: Workspace) -> ToolResult:
    process = await asyncio.create_subprocess_exec("git", "-C", str(workspace.root), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate(); out = stdout.decode(errors="replace").strip(); err = stderr.decode(errors="replace").strip()
    return ToolResult(process.returncode == 0, output=out, stdout=out, stderr=err, exit_code=process.returncode, error=err if process.returncode else "")

def coding_registry(registry: ToolRegistry, workspace: Workspace) -> None:
    text = {"type": "string"}
    registry.register(Tool("read_file", "Read up to 200 lines from a UTF-8 workspace file.", {"type":"object","properties":{"path":text,"line_start":{"type":"integer","default":1},"line_end":{"type":"integer"}},"required":["path"]}, lambda path, line_start=1, line_end=None: read_file(path, workspace, line_start, line_end)))
    registry.register(Tool("list_dir", "Compatibility alias for list_directory.", {"type":"object","properties":{"path":text,"limit":{"type":"integer","default":200}}}, lambda path=".", limit=200: list_directory(path, workspace, limit)))
    registry.register(Tool("list_directory", "List bounded workspace directory entries.", {"type":"object","properties":{"path":text,"limit":{"type":"integer","default":200}}}, lambda path=".", limit=200: list_directory(path, workspace, limit)))
    for name, function, description in (("write_file", write_file, "Overwrite a workspace text file."),("create_file", create_file, "Create a new workspace text file.")):
        registry.register(Tool(name, description, {"type":"object","properties":{"path":text,"content":text},"required":["path","content"]}, lambda path, content, function=function: function(path, content, workspace), capability="file.write", permission_level=PermissionLevel.CONFIRM))
    registry.register(Tool("edit_file", "Replace one unique text block in a workspace file.", {"type":"object","properties":{"path":text,"old_text":text,"new_text":text},"required":["path","old_text","new_text"]}, lambda path, old_text, new_text: edit_file(path, old_text, new_text, workspace), capability="file.write", permission_level=PermissionLevel.CONFIRM))
    registry.register(Tool("find_files", "Find bounded workspace files by filename glob.", {"type":"object","properties":{"pattern":text},"required":["pattern"]}, lambda pattern: find_files(pattern, workspace)))
    registry.register(Tool("search_files", "Search bounded workspace text and return file, line, and content.", {"type":"object","properties":{"query":text,"path":{"type":"string","default":"."},"limit":{"type":"integer","default":200}},"required":["query"]}, lambda query, path=".", limit=200: search_files(query, path, workspace, limit)))
    for name, args in (("git_status", ["status", "--short"]),("git_diff", ["diff"]),("git_log", ["log", "-10", "--oneline"])):
        registry.register(Tool(name, f"Show Git {name.removeprefix('git_')}.", {"type":"object","properties":{}}, lambda args=args: _git(args, workspace)))
