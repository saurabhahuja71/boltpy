"""Project metadata and instruction discovery for Bolt."""
from __future__ import annotations
from pathlib import Path

_METADATA = ("README.md", "pyproject.toml", "package.json", "go.mod", "Cargo.toml", "requirements.txt")
_INSTRUCTIONS = ("AGENTS.md", "BOLT.md", "CONTRIBUTING.md")

def project_context(root: Path) -> str:
    root = root.resolve()
    lines = [f"Workspace: {root}"]
    if (root / ".git").exists(): lines.append("Git repository: yes")
    metadata = [name for name in _METADATA if (root / name).is_file()]
    lines.append("Project metadata: " + (", ".join(metadata) if metadata else "none detected"))
    instructions = [name for name in _INSTRUCTIONS if (root / name).is_file()]
    lines.append("Instruction files: " + (", ".join(instructions) if instructions else "none detected"))
    return "\n".join(lines)

def instruction_text(root: Path) -> str:
    chunks=[]
    for name in _INSTRUCTIONS:
        path=root/name
        if path.is_file():
            try: chunks.append(f"## {name}\n{path.read_text(encoding='utf-8')}")
            except OSError: pass
    return "\n\n".join(chunks)
