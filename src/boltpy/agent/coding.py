"""Workspace-scoped coding and Git tools for Bolt."""
from __future__ import annotations
import asyncio
from pathlib import Path
from boltpy.agent.tools import Tool, ToolRegistry, ToolResult

class Workspace:
    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).expanduser().resolve()
    def path(self, value: str) -> Path:
        candidate = (self.root / value).resolve() if not Path(value).is_absolute() else Path(value).expanduser().resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError(f"Path escapes workspace: {value}")
        return candidate
    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

def _text(path: Path) -> str:
    try: return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error: raise ValueError(f"File is not UTF-8 text: {path}") from error

def read_file(path: str, workspace: Workspace) -> str:
    target=workspace.path(path)
    if not target.is_file(): raise FileNotFoundError(path)
    return _text(target)

def list_directory(path: str, workspace: Workspace) -> str:
    target=workspace.path(path)
    if not target.is_dir(): raise NotADirectoryError(path)
    return "\n".join(f"{item.name}{'/' if item.is_dir() else ''}" for item in sorted(target.iterdir(), key=lambda x:x.name.lower())) or "(empty directory)"

def write_file(path: str, content: str, workspace: Workspace) -> str:
    target=workspace.path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8"); return f"Wrote {workspace.rel(target)} ({len(content)} bytes)"

def create_file(path: str, content: str, workspace: Workspace) -> str:
    target=workspace.path(path)
    if target.exists(): raise FileExistsError(path)
    return write_file(path, content, workspace)

def edit_file(path: str, old_text: str, new_text: str, workspace: Workspace) -> str:
    target=workspace.path(path); current=_text(target)
    count=current.count(old_text)
    if count == 0: raise ValueError("old_text was not found")
    if count > 1: raise ValueError("old_text matched multiple locations; provide a larger unique block")
    target.write_text(current.replace(old_text, new_text), encoding="utf-8")
    return f"Edited {workspace.rel(target)}"

def find_files(pattern: str, workspace: Workspace) -> str:
    matches=[workspace.rel(p) for p in workspace.root.rglob(pattern) if not any(part in {".git",".venv","node_modules","__pycache__"} for part in p.parts)]
    return "\n".join(sorted(matches)) or "(no files found)"

def search_files(query: str, path: str, workspace: Workspace) -> str:
    if not query.strip(): raise ValueError("query cannot be empty")
    base=workspace.path(path); results=[]
    for file in base.rglob("*") if base.is_dir() else [base]:
        if not file.is_file() or any(part in {".git",".venv","node_modules","__pycache__"} for part in file.parts): continue
        try: lines=_text(file).splitlines()
        except (OSError, ValueError): continue
        for number,line in enumerate(lines,1):
            if query.casefold() in line.casefold(): results.append(f"{workspace.rel(file)}:{number}:{line.strip()}")
            if len(results)>=200: return "\n".join(results)+"\n(results limited to 200 matches)"
    return "\n".join(results) or "(no matches)"

async def _git(args: list[str], workspace: Workspace) -> ToolResult:
    process=await asyncio.create_subprocess_exec("git", "-C", str(workspace.root), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout,stderr=await process.communicate(); out=stdout.decode(errors="replace").strip(); err=stderr.decode(errors="replace").strip()
    return ToolResult(process.returncode==0, output=out, stdout=out, stderr=err, exit_code=process.returncode, error=err if process.returncode else "")

def coding_registry(registry: ToolRegistry, workspace: Workspace) -> None:
    text={"type":"string"}
    registry.register(Tool("read_file","Read a UTF-8 text file in the workspace.",{"type":"object","properties":{"path":text},"required":["path"]},lambda path: read_file(path,workspace)))
    registry.register(Tool("list_dir","Compatibility alias for list_directory.",{"type":"object","properties":{"path":text}},lambda path=".": list_directory(path,workspace)))
    registry.register(Tool("list_directory","List entries in the workspace.",{"type":"object","properties":{"path":text}},lambda path=".": list_directory(path,workspace)))
    registry.register(Tool("write_file","Overwrite a workspace text file.",{"type":"object","properties":{"path":text,"content":text},"required":["path","content"]},lambda path,content: write_file(path,content,workspace),capability="file.write"))
    registry.register(Tool("create_file","Create a new workspace text file.",{"type":"object","properties":{"path":text,"content":text},"required":["path","content"]},lambda path,content: create_file(path,content,workspace),capability="file.write"))
    registry.register(Tool("edit_file","Replace one unique text block in a workspace file.",{"type":"object","properties":{"path":text,"old_text":text,"new_text":text},"required":["path","old_text","new_text"]},lambda path,old_text,new_text: edit_file(path,old_text,new_text,workspace),capability="file.write"))
    registry.register(Tool("find_files","Find workspace files by glob.",{"type":"object","properties":{"pattern":text},"required":["pattern"]},lambda pattern: find_files(pattern,workspace)))
    registry.register(Tool("search_files","Search case-insensitive text in workspace files.",{"type":"object","properties":{"query":text,"path":{"type":"string","default":"."}},"required":["query"]},lambda query,path=".": search_files(query,path,workspace)))
    for name,args in (("git_status",["status","--short"]),("git_diff",["diff"]),("git_log",["log","-10","--oneline"])):
        registry.register(Tool(name,f"Show Git {name.removeprefix('git_')}.",{"type":"object","properties":{}},lambda args=args: _git(args,workspace)))
