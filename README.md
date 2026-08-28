# Bolt — a terminal-native AI coding agent

Bolt is a fast, keyboard-first terminal AI agent for inspecting projects, running local commands, and checking remote systems over SSH. It streams model responses, uses OpenAI-compatible APIs, and keeps tool execution behind clear, asynchronous permissions.

Built for developers who want a practical AI assistant in the terminal—not a web dashboard.

## Quick start

```bash
uv run bolt
uv run bolt ask "What is 2+2?"
uv run bolt exec "summarize the README"
```

Set `OPENAI_API_KEY` for OpenAI or point `OPENAI_BASE_URL` at an OpenAI-compatible service. Bolt reads configuration in this order: defaults, `~/.config/boltpy/config.toml`, local `bolt.toml`, then environment variables.

```toml
provider = "openai"
model = "gpt-4o-mini"
# Optional selector entries; the active model is always included.
models = ["gpt-4o-mini", "local-model"]
permission_mode = "ask"
theme = "light"
```

Equivalent environment variables include `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `BOLT_PROVIDER`, `BOLT_MODELS` (comma-separated), `BOLT_PERMISSION_MODE`, and `BOLT_THEME`.

## Providers

Bolt uses a clean provider abstraction. Any OpenAI-compatible API (OpenAI, OpenRouter, xAI, DeepSeek, vLLM, SGLang…) works through `OpenAICompatibleProvider`; set `provider = "openai"` (or the service name) and optionally `base_url`. Local Ollama daemons use `provider = "ollama"` and need no API key — the provider points at `http://localhost:11434/v1` by default (override with `base_url` or `OLLAMA_BASE_URL`). Override either per-invocation with `--provider` and `--model`.

## Tools, tasks, and safe permissions

Bolt’s reusable tool registry includes:

- `read_file(path)` — read UTF-8 text.
- `list_dir(path)` — list a directory.
- `run_shell(command, timeout)` — execute a bounded local shell command.
- `ssh(host, command, user, port, timeout)` — execute a non-interactive command with the system `ssh` client.
- `http_request(method, url, headers, body, timeout)` — perform an HTTP(S) request with a bounded timeout and clear errors, useful for web APIs such as GitLab.
- `add_todo` / `complete_todo` / `update_todo` / `list_todos` — maintain the live todo side panel.
- `present_options(title, options)` — ask the user to pick from a numbered menu.

For every submitted chat task, Bolt adds a parent item to the live todo panel. Multi-step work can add subtasks with `add_todo`; completed items remain visible, while failed or cancelled parent tasks remain open for follow-up. Tool progress is shown in the status bar, without noisy tool cards in the transcript.

Interactive mode defaults to `ask`: read-only tools run directly, while shell and SSH actions show an inline approval prompt. The prompt supports Allow Once, Allow Session, Allow Permanently, and Deny. Safety validation always runs before permission lookup, so a saved approval can never authorize a blocked catastrophic command.

`plan` mode is the read-first workflow: read-only tools run freely, but write, shell, and SSH actions are blocked so the agent must propose a step-by-step plan instead. Switch with `/mode plan` and return to `ask` or `allow` to let it execute.

Permanent approvals are exact and human-readable in `~/.config/boltpy/permissions.toml`; SSH approvals include host, user, port, and command. Inspect or remove them inside Bolt:

```text
/permissions
/permissions remove "git status"
```

Headless `exec` mode uses `allow` automatically, which makes it suitable for scripts and automation without importing Textual or opening a prompt.

## Model selection

Configure available model names with `models` or `BOLT_MODELS`, then use `/model` in the TUI. When the local `ollama` executable is available, Bolt also discovers installed names from `ollama list` automatically. The compact selector supports mouse selection, arrow keys, Enter to activate, and Escape to cancel. The active provider and model are shown in the status bar and apply to subsequent requests without restarting Bolt.

## Terminal UI

The TUI has a single chat transcript on the left with a collapsible todo side panel on the right; streaming text renders into the transcript, with the status bar and input at the bottom. It provides streaming Textual Markdown with syntax-highlighted fenced code, tables, lists, links, a CSS-variable theme system with light theme by default, a live todo side panel, a numbered options picker with a typed answer, inline permission controls, a visible `CWD:` line at the top, and a status bar formatted as `Bolt | Mode: ASK/ALLOW/PLAN | Mouse: INTERACTIVE/SELECT | Model: provider/model | Tokens: n`.

### Chat commands

```text
/help
/model
/mode ask|allow|plan
/todo
/queue
/permissions
/theme dark|light
/mouse interactive|select
/new
/quit
```

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Shift+S` | Show all commands and shortcuts |
| `Ctrl+Shift+M` | Cycle permission mode: ASK → ALLOW → PLAN |
| `Ctrl+Shift+T` | Toggle the todo panel |
| `Ctrl+Shift+I` | Toggle interactive cursor/mouse mode and native text selection |
| `Ctrl+C` | Cancel the current task; queued prompts continue afterward |
| `Ctrl+Q` | Quit |
| `Enter` | Send the prompt |
| `Shift+Enter` | Insert a newline |

Prompts sent while a task is running are queued and run in order when it finishes; the status bar shows the number waiting and `/queue` lists them.

Text selection and clipboard behavior remain terminal-native. Interactive cursor mode is the default: mouse clicks and scrolling work on widgets such as permission/model buttons. Use `/mouse select` or `Ctrl+Shift+I` when you need native terminal selection — drag across conversation text and use the terminal’s copy/paste shortcuts, commonly Ctrl+Shift+C / Ctrl+Shift+V or Shift+Insert — then return with `/mouse interactive` or `Ctrl+Shift+I`.

### Example prompts

Bolt can handle direct questions, local project inspection, remote diagnostics, and API checks. Examples:

```text
Summarize the README and list the three most important setup steps.
Inspect the current Git status and explain any uncommitted changes.
Connect to podman9, list running containers, stop only racnode containers, and verify DNS remains running.
Check the GitLab pipeline at this URL and report the failed job with its log summary.
Read the deployment manifest and propose a plan without making changes.
```

For remote work, mention the host, user, and exact desired operation. Bolt uses the system SSH client and asks before shell or SSH actions in `ask` mode.

### Local launchers

If your shell defines the optional backend helpers, the dedicated launchers can be used as follows:

```bash
bolt-s1 ask "inspect this project"   # Ollama backend
bolt-s2 ask "inspect this project"   # SGLang backend
```

These aliases are environment-specific; standard Bolt installations use `uv run bolt` instead.

## SSH boundaries

SSH uses the system executable and the user’s existing `~/.ssh/config`, keys, ssh-agent, and known-hosts checks. Bolt does not manage credentials or private keys. Commands run without an interactive TTY; programs requiring a full interactive session are intentionally reported as unsupported rather than allowed to hang the agent. Local and remote commands capture stdout, stderr, exit status, duration, timeout, and cancellation state.

Use `--debug` with `ask` or `exec` to print concise tool-loop diagnostics to stderr without exposing credentials or tokens. `ask` and `exec` also accept `--model` and `--provider` to override the configured values for a single run.

## Development

```bash
uv sync --dev
uv run --dev pytest
uv run python -m compileall -q src
```

Bolt keeps the headless execution path independent from Textual, so automation remains lightweight and testable.
