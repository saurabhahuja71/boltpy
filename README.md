# Boltpy — a terminal-native AI coding agent

Boltpy is a fast, keyboard-first terminal AI agent for inspecting projects, running local commands, and checking remote systems over SSH. It streams model responses, uses OpenAI-compatible APIs, and keeps tool execution behind clear, asynchronous permissions.

Built for developers who want a practical AI assistant in the terminal—not a web dashboard.

## Quick start

```bash
uv run boltpy
uv run boltpy ask "What is 2+2?"
uv run boltpy exec "summarize the README"
```

Set `OPENAI_API_KEY` for OpenAI or point `OPENAI_BASE_URL` at an OpenAI-compatible service. Boltpy reads configuration in this order: defaults, `~/.config/boltpy/config.toml`, local `boltpy.toml`, then environment variables.

```toml
model = "gpt-4o-mini"
# Optional selector entries; the active model is always included.
models = ["gpt-4o-mini", "local-model"]
permission_mode = "ask"
```

Equivalent environment variables include `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `BOLTPY_MODELS` (comma-separated), and `BOLTPY_PERMISSION_MODE`.

## Tools and safe permissions

Boltpy’s reusable tool registry includes:

- `read_file(path)` — read UTF-8 text.
- `list_dir(path)` — list a directory.
- `run_shell(command, timeout)` — execute a bounded local shell command.
- `ssh(host, command, user, port, timeout)` — execute a non-interactive command with the system `ssh` client.

Interactive mode defaults to `ask`: read-only tools run directly, while shell and SSH actions show an inline approval prompt. The prompt supports Allow Once, Allow Session, Allow Permanently, and Deny. Safety validation always runs before permission lookup, so a saved approval can never authorize a blocked catastrophic command.

Permanent approvals are exact and human-readable in `~/.config/boltpy/permissions.toml`; SSH approvals include host, user, port, and command. Inspect or remove them inside Boltpy:

```text
/permissions
/permissions remove "git status"
```

Headless `exec` mode uses `allow` automatically, which makes it suitable for scripts and automation without importing Textual or opening a prompt.

## Model selection

Configure available model names with `models` or `BOLTPY_MODELS`, then use `/model` in the TUI. The compact selector supports mouse selection, arrow keys, Enter to activate, and Escape to cancel. The active model is shown in the status bar and applies to subsequent requests without restarting Boltpy.

## Terminal UI

The TUI provides streaming Markdown with syntax-highlighted fenced code, tables, lists, links, compact tool cards, light/dark themes, natural scrolling, and inline permission controls. Useful commands:

```text
/help
/model
/mode ask|allow
/permissions
/theme dark|light
/mouse select|interactive
/new
/quit
```

Text selection and clipboard behavior remain terminal-native. Use `/mouse select` (or Ctrl+Shift+M) to release Textual mouse reporting and select conversation text with normal left-drag behavior; use the terminal’s copy/paste shortcuts, commonly Ctrl+Shift+C / Ctrl+Shift+V or Shift+Insert. `/mouse interactive` restores widget clicks and scrolling, including permission and model-selector buttons.

## SSH boundaries

SSH uses the system executable and the user’s existing `~/.ssh/config`, keys, ssh-agent, and known-hosts checks. Boltpy does not manage credentials or private keys. Commands run without an interactive TTY; programs requiring a full interactive session are intentionally reported as unsupported rather than allowed to hang the agent. Local and remote commands capture stdout, stderr, exit status, duration, timeout, and cancellation state.

Use `--debug` with `ask` or `exec` to print concise tool-loop diagnostics to stderr without exposing credentials or tokens.

## Development

```bash
uv sync --dev
uv run --dev pytest
uv run python -m compileall -q src
```

Boltpy keeps the headless execution path independent from Textual, so automation remains lightweight and testable.
