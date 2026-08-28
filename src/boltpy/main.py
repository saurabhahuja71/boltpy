"""Console entry point for Bolt."""
from __future__ import annotations
import sys
from pathlib import Path
from boltpy.cli import run

def main() -> None:
    # Support the terminal-native `bolt .` form alongside Typer commands.
    args = sys.argv[1:]
    if args and not args[0].startswith("-") and args[0] not in {"ask", "exec", "models"}:
        candidate = Path(args[0])
        if candidate.is_dir():
            sys.argv[1:] = ["--project", args[0], *args[1:]]
    run()

if __name__ == "__main__":
    main()
