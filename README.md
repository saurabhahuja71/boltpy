# Boltpy

Boltpy is a streaming terminal coding agent built with Python 3.12+, Textual, and the official async OpenAI SDK.

```bash
uv run boltpy
uv run boltpy ask "What is 2+2?"
```

Set `OPENAI_API_KEY` for OpenAI, or use any compatible service with `OPENAI_BASE_URL` and `OPENAI_MODEL` (for example, Ollama at `http://localhost:11434/v1`). Configuration loads defaults, `~/.config/boltpy/config.toml`, local `boltpy.toml`, then environment variables. The TUI supports `/new`, `/help`, and `/quit`.
