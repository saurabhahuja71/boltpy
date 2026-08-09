# Boltpy

Boltpy is a streaming terminal coding agent built with Python 3.12+, Textual, and the official async OpenAI SDK.

```bash
uv run boltpy
uv run boltpy ask "What is 2+2?"
```

Set `OPENAI_API_KEY` for OpenAI, or use any compatible service with `OPENAI_BASE_URL` and `OPENAI_MODEL` (for example, Ollama at `http://localhost:11434/v1`). Configuration loads defaults, `~/.config/boltpy/config.toml`, local `boltpy.toml`, then environment variables. The TUI supports `/new`, `/help`, and `/quit`.

## Tools and permissions

Phase 2 adds `read_file`, `list_dir`, and `run_shell` through an extensible tool registry. The interactive app starts in `ask` mode; `list_dir` and `read_file` are read-only, while `run_shell` requires approval; use `/mode allow` or `/mode ask` to switch. Configure the initial mode with `BOLTPY_PERMISSION_MODE` or `permission_mode` in `boltpy.toml`.

Headless execution enables tools by default:

```bash
uv run boltpy exec "summarize the README"
uv run boltpy exec "list all python files"
```

Potentially destructive shell commands are blocked, and tool failures are returned to the model as tool results so it can explain or recover.
