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
provider = "openai"
model = "gpt-4o-mini"
# Optional selector entries; the active model is always included.
models = ["gpt-4o-mini", "local-model"]
permission_mode = "ask"
theme = "dark"
```

Equivalent environment variables include `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `BOLTPY_PROVIDER`, `BOLTPY_MODELS` (comma-separated), `BOLTPY_PERMISSION_MODE`, and `BOLTPY_THEME`.

## Providers

Boltpy uses a clean provider abstraction. Any OpenAI-compatible API (OpenAI, OpenRouter, xAI, DeepSeek, vLLM, SGLang…) works through `OpenAICompatibleProvider`; set `provider = "openai"` (or the service name) and optionally `base_url`. Local Ollama daemons use `provider = "ollama"` and need no API key — the provider points at `http://localhost:11434/v1` by default (override with `base_url` or `OLLAMA_BASE_URL`). Override either per-invocation with `--provider` and `--model`.

## Tools and safe permissions

Boltpy’s reusable tool registry includes:

- `read_file(path)` — read UTF-8 text.
- `list_dir(path)` — list a directory.
- `run_shell(command, timeout)` — execute a bounded local shell command.
- `ssh(host, command, user, port, timeout)` — execute a non-interactive command with the system `ssh` client.
- `http_request(method, url, headers, body, timeout)` — perform an HTTP(S) request with a bounded timeout and clear errors, useful for web APIs such as GitLab.
- `add_todo` / `complete_todo` / `update_todo` / `list_todos` — maintain the live todo side panel.
- `present_options(title, options)` — ask the user to pick from a numbered menu.

Interactive mode defaults to `ask`: read-only tools run directly, while shell and SSH actions show an inline approval prompt. The prompt supports Allow Once, Allow Session, Allow Permanently, and Deny. Safety validation always runs before permission lookup, so a saved approval can never authorize a blocked catastrophic command.

`plan` mode is the read-first workflow: read-only tools run freely, but write, shell, and SSH actions are blocked so the agent must propose a step-by-step plan instead. Switch with `/mode plan` and return to `ask` or `allow` to let it execute.

Permanent approvals are exact and human-readable in `~/.config/boltpy/permissions.toml`; SSH approvals include host, user, port, and command. Inspect or remove them inside Boltpy:

```text
/permissions
/permissions remove "git status"
```

Headless `exec` mode uses `allow` automatically, which makes it suitable for scripts and automation without importing Textual or opening a prompt.

## Model selection

Configure available model names with `models` or `BOLTPY_MODELS`, then use `/model` in the TUI. When the local `ollama` executable is available, Boltpy also discovers installed names from `ollama list` automatically. The compact selector supports mouse selection, arrow keys, Enter to activate, and Escape to cancel. The active provider and model are shown in the status bar and apply to subsequent requests without restarting Boltpy.

## Terminal UI

The TUI provides streaming Textual Markdown with syntax-highlighted fenced code, tables, lists, links, collapsible tool cards with running/success/failed/denied states, a CSS-variable theme system with dark/light themes, a live todo side panel (`Ctrl+T` or `/todo`), a numbered options picker with a typed answer, inline permission controls, a visible `CWD:` line at the top, and a status bar formatted as `Boltpy | Mode: ASK/ALLOW/PLAN | Model: provider/model | Tokens: n`. Useful commands:

```text
/help
/model
/mode ask|allow|plan
/todo
/permissions
/theme dark|light
/mouse interactive|select
/new
/quit
```

Text selection and clipboard behavior remain terminal-native. Interactive mode is the default: mouse clicks and scrolling work on widgets such as permission/model buttons. Use `/mouse select` when you need native terminal selection — drag across conversation text and use the terminal’s copy/paste shortcuts, commonly Ctrl+Shift+C / Ctrl+Shift+V or Shift+Insert — then return with `/mouse interactive`; Ctrl+M toggles between both modes.

## SSH boundaries

SSH uses the system executable and the user’s existing `~/.ssh/config`, keys, ssh-agent, and known-hosts checks. Boltpy does not manage credentials or private keys. Commands run without an interactive TTY; programs requiring a full interactive session are intentionally reported as unsupported rather than allowed to hang the agent. Local and remote commands capture stdout, stderr, exit status, duration, timeout, and cancellation state.

Use `--debug` with `ask` or `exec` to print concise tool-loop diagnostics to stderr without exposing credentials or tokens. `ask` and `exec` also accept `--model` and `--provider` to override the configured values for a single run.

## Development

```bash
uv sync --dev
uv run --dev pytest
uv run python -m compileall -q src
```

Boltpy keeps the headless execution path independent from Textual, so automation remains lightweight and testable.
