# Boltpy continuity

- Summary: Boltpy Phase 1, Phase 2, Phase 3, and the practical shell/SSH functionality are complete; this checkout also includes model switching and scoped permanent permissions.
- Architecture: the existing Agent → ToolRegistry → PermissionManager → TUI adapter remains intact. Local shell and system-SSH tools validate safety before asynchronous permission checks and return structured results.
- New user features: `/model` selects configured models from an inline keyboard/mouse OptionList; `/permissions` lists exact persistent grants and `/permissions remove "command"` removes one. Permanent approvals are stored in `~/.config/boltpy/permissions.toml`, with SSH scopes including host, user, port, and command.
- TUI behavior: inline Allow Once / Allow Session / Allow Permanently / Deny remains asynchronous and compact. native terminal selection is the default; `/mouse interactive` restores widget clicks and scrolling, and `/mouse select` returns to selection mode.
- Validation: `uv run --dev pytest -q` passes 25 tests; compileall, CLI help, headless-import, and `git diff --check` pass.
- Release: package version is 1.0.0; commit `398a38b` is pushed to `main`; GitHub `v1.0.0` is published at https://github.com/saurabhahuja71/boltpy/releases/tag/v1.0.0.
- Known limitations: SSH is non-interactive and uses the system client; live provider validation depends on the configured endpoint/model and tool-call support.
