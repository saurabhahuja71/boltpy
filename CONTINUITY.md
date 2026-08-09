# Boltpy continuity

- Summary: Implemented Phase 1 foundation: Typer CLI, config loading, async OpenAI-compatible streaming agent, Textual chat UI, and focused tests.
- Files modified: `pyproject.toml`, `README.md`, `src/boltpy/`, `tests/`, `uv.lock`.
- Decisions: Conventional `__init__.py` package files; config precedence is defaults, user TOML, local TOML, environment; TUI submits multiline prompts with Ctrl+Enter.
- Validation: `uv run --dev pytest` passes (3 tests); CLI help passes; headless import check confirms Textual is not imported.
- Known issue: Live `ask` validation depends on the configured endpoint/model; current environment endpoint returned model-not-found for `gpt-4o-mini`.
- Local launchers: `~/.bashrc` now provides `bolt-s1` for Ollama on `:11435` and `bolt-s2` for SGLang on `:30002`; both run the backend ensure helper before `uv run`.
- Suggested next task: Add provider/model discovery and Phase 2 tool permission modes.
