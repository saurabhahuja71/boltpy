# Changelog

## 1.1.19

- Include `/remap` in slash-command suggestions.
- Ensure `/remap` lists the default Ctrl+Y permission-mode shortcut.


## 1.1.18

- Add `/remap` to change, list, and reset live keyboard shortcuts.
- Remapped shortcuts are reflected immediately in the footer.


## 1.1.17

- Show Ctrl+Y/T/L as the primary mode, todos, and mouse shortcuts instead of F-key fallbacks.


## 1.1.16

- Map theme selection to Ctrl+B.


## 1.1.15

- Use confirmed terminal Ctrl+C/L/G/P controls instead of unreliable Alt shortcuts.
- Restore normal typing by removing ESC-prefix shortcut parsing.


## 1.1.14

- Remove obsolete top-left helper and CWD display.
- Restore the standard shortcut footer.
- Document all implemented slash commands, including `/clear` and `/provider`.


## 1.1.13

- Restore the standard shortcut footer and remove the top-left shortcut bar.
- Show the current working directory immediately above the footer.
- Improve Alt shortcut handling for VS Code terminal events.


## 1.1.12

- Display shortcut operation names before their key combinations consistently.


## 1.1.11

- Use MATE-confirmed Alt+P for theme selection and direct ESC+Q exit handling.
- Display shortcuts with the key before the operation name.


## 1.1.10

- Put shortcut operation names before their key combinations for clearer display.


## 1.1.9

- Remap MATE-safe Alt shortcuts to keys confirmed to pass through the terminal.


## 1.1.8

- Handle MATE Terminal Alt shortcuts emitted as ESC plus a letter.


## 1.1.7

- Render slash-command suggestions directly below the prompt.


## 1.1.6

- Show filtered slash-command suggestions while typing.
- Use Windows/Super-key shortcuts instead of Alt shortcuts.


## 1.1.5

- Print the active Alt and function-key shortcuts in the TUI shortcut bar.


## 1.1.4

- Use Alt-only application shortcuts for consistent terminal behavior.


## 1.1.3

- Handle Ctrl+Alt shortcuts directly from the prompt for MATE Terminal compatibility.


## 1.1.2

- Made `bolt upgrade` stream download and installer progress live.
- Made the curl installer show each installation phase and detailed failure location.


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
