# Changelog

## 1.1.1

- Added a dark/black default theme and interactive `/theme` selector.
- Added terminal-safe F2-F5 shortcuts plus Ctrl+Alt aliases for VS Code and normal terminals.
- Added `/exit` as an alias for `/quit`.
- Added the built-in `bolt upgrade` command.


## 1.1.0

### What's New

- Added a real multi-step coding-agent workflow with repository exploration, safe targeted edits, command execution, validation, and Git diff support.
- Added bounded workspace tools for listing, finding, searching, and reading files.
- Added atomic file writes and workspace path/symlink safety checks.
- Added structured command results with stdout, stderr, exit codes, timing, timeouts, and cancellation handling.
- Added the run_command workspace-scoped tool while preserving run_shell compatibility.
- Added global CLI options for model, provider, endpoint, version, and help.
- Added bolt doctor and a no-sudo isolated installer for public command-line installation.
- Fixed todo lifecycle identifiers so tools return and accept stable opaque IDs while UI numbering remains display-only.
- Preserved existing Ollama, OpenAI-compatible provider, permission, todo, UI, and keyboard shortcut behavior.

### Verification

- Full pytest regression suite passed.
- Direct filesystem, command, and Git tool checks passed.
- Live Ollama model discovery and an isolated end-to-end coding task passed.
- Package installation and execution outside the source tree passed.
