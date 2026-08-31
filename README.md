# Bolt — a terminal-native AI coding agent

Bolt is a fast, keyboard-first terminal AI agent for inspecting projects, running local commands, and checking remote systems over SSH. It streams model responses, uses OpenAI-compatible APIs, and keeps tool execution behind clear, asynchronous permissions.

Built for developers who want a practical AI assistant in the terminal—not a web dashboard.


## Local & Self-Hosted Models

Bolt is a local-first coding agent designed to work with local and self-hosted LLM inference servers. Your code and prompts can stay within infrastructure you control.

Supported backends include:

- **Ollama**
  - Local Ollama servers
  - Remote Ollama servers

- **SGLang**
  - Local SGLang servers
  - Remote SGLang servers
  - OpenAI-compatible API endpoints

- **Other OpenAI-compatible inference servers** where compatible with Bolt's provider implementation, including compatible vLLM, LM Studio, and similar deployments.

Bolt is not dependent on a cloud LLM provider. You can run it against your own workstation, a private server, or remote inference infrastructure on your network.

### Ollama

Local Ollama:

```bash
bolt --provider ollama \
  --endpoint http://localhost:11434 \
  --model qwen3-coder
```

Remote Ollama:

```bash
bolt --provider ollama \
  --endpoint http://ollama.internal:11434 \
  --model qwen3-coder
```

You can also configure Ollama with `OLLAMA_HOST`, `OLLAMA_BASE_URL`, or a Bolt config file. Bolt discovers models from the configured Ollama server with `bolt models`.

### SGLang

Local SGLang with its OpenAI-compatible endpoint:

```bash
bolt --provider sglang \
  --endpoint http://localhost:30000/v1 \
  --model Qwen/Qwen3-Coder
```

Remote SGLang:

```bash
bolt --provider sglang \
  --endpoint http://inference.internal:30000/v1 \
  --model Qwen/Qwen3-Coder
```

For an OpenAI-compatible self-hosted server, point `--endpoint` at its compatible `/v1` API endpoint and select the provider name used by your configuration:

```bash
bolt --provider my-server \
  --endpoint http://inference.internal:8000/v1 \
  --model my-coding-model
```


## Install Bolt

Install for the current user with:

```bash
curl -fsSL https://raw.githubusercontent.com/saurabhahuja71/boltpy/main/install.sh | bash
```

The installer prints progress for Python detection, source download, environment creation, and dependency installation. It searches for Python 3.12 or newer (including versioned commands such as `python3.12`), then creates an isolated environment under `~/.local/share/bolt` and places the command in `~/.local/bin`. If [uv](https://docs.astral.sh/uv/) is installed, it can download a compatible Python automatically without sudo. Set `PYTHON=/path/to/python` to choose a specific interpreter.

## Usage

bolt
bolt .
bolt /path/to/project
bolt --model qwen3-coder
bolt --provider ollama --endpoint http://localhost:11434
bolt doctor

For development, use pip install -e . or uv run bolt. To upgrade an existing installation in place, run `bolt upgrade`; it streams download and installation progress and uses the same user-local installer as the curl command.

Set `OPENAI_API_KEY` for OpenAI or point `OPENAI_BASE_URL` at an OpenAI-compatible service. Bolt reads configuration in this order: defaults, `~/.config/boltpy/config.toml`, local `bolt.toml`, then environment variables.

```toml
provider = "openai"
model = "gpt-4o-mini"
# Optional selector entries; the active model is always included.
models = ["gpt-4o-mini", "local-model"]
permission_mode = "ask"
theme = "dark"
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

The TUI has a single chat transcript on the left with a collapsible todo side panel on the right; streaming text renders into the transcript, with the status bar and input at the bottom. It provides streaming Textual Markdown with syntax-highlighted fenced code, tables, lists, links, a CSS-variable theme system with dark/black theme by default, a live todo side panel, a numbered options picker with a typed answer, inline permission controls, and a status bar formatted as `Bolt | Mode: ASK/ALLOW/PLAN | Mouse: INTERACTIVE/SELECT | Model: provider/model | Tokens: n`.

### Chat commands

```text
/help
/model
/mode ask|allow|plan
/todo
/queue
/clear
/permissions
/theme
/theme dark|light
/mouse interactive|select
/new
/quit
/exit
/upgrade (CLI)
```

### Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| Show all commands and shortcuts | `Alt+R` |
| Cycle permission mode: ASK → ALLOW → PLAN | `Alt+Y` |
| Toggle the todo panel | `Alt+U` |
| Toggle interactive cursor/mouse mode and native text selection | `Alt+I` |
| Cancel the current task; queued prompts continue afterward | `Alt+C` |
| Quit | `Alt+Q` |
| `Enter` | Send the prompt |
| `Shift+Enter` | Insert a newline |

The standard shortcut footer is shown at the bottom of the TUI. Slash-command suggestions appear directly below the prompt. Run `/theme` or press `Alt+P` to open the interactive dark/light selector. `F3`, `F4`, and `F5` switch permission mode, todos, and mouse mode. Typing `/` shows filtered available commands. Function keys and slash commands work in VS Code and normal terminals; Alt shortcuts are handled from the prompt as well as globally for better MATE Terminal compatibility.

Prompts sent while a task is running are queued and run in order when it finishes; the status bar shows the number waiting and `/queue` lists them.

Text selection and clipboard behavior remain terminal-native. Interactive cursor mode is the default: mouse clicks and scrolling work on widgets such as permission/model buttons. Use `/mouse select` or `Alt+I` when you need native terminal selection — drag across conversation text and use the terminal’s copy/paste shortcuts, commonly Alt+C / Win+V or Shift+Insert — then return with `/mouse interactive` or `Alt+I`.

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
