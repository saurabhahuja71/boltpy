"""Configuration loading for Boltpy."""
from __future__ import annotations
import os
import tomllib
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class Settings(BaseModel):
    """Runtime settings for Boltpy providers and the TUI."""
    model_config = ConfigDict(extra="ignore")
    provider: str = "ollama"
    model: str = "gpt-4o-mini"
    models: list[str] = Field(default_factory=list)
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    system_prompt: str = "You are Boltpy, a helpful terminal coding assistant."
    permission_mode: Literal["ask", "allow", "plan"] = "ask"
    theme: str = "dark"
    workspace: Path = Field(default_factory=Path.cwd)
    first_launch: bool = False
    mouse_mode: Literal["interactive", "select"] = "select"
    vision_enabled: bool | None = None
    # Conversation history is opt-in at process startup.  This is deliberately
    # separate from the session store so persistence never implies restoration.
    resume: bool = False

    def available_models(self) -> list[str]:
        """Return configured models with the active model first."""
        return list(dict.fromkeys([self.model, *self.models]))

def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as file:
        value = tomllib.load(file)
    return value if isinstance(value, dict) else {}

_ENV_FIELDS = {
    "OPENAI_API_KEY": "api_key",
    "OPENAI_BASE_URL": "base_url",
    "OPENAI_MODEL": "model",
    "BOLT_MODEL": "model",
    "OPENAI_PROVIDER": "provider",
    "BOLT_PROVIDER": "provider",
    "BOLT_ENDPOINT": "base_url",
    "BOLT_WORKSPACE": "workspace",
    "BOLT_MOUSE_MODE": "mouse_mode",
    "BOLTPY_PROVIDER": "provider",
    "BOLTPY_MODELS": "models",
    "BOLTPY_PERMISSION_MODE": "permission_mode",
    "BOLTPY_THEME": "theme",
    "BOLTPY_VISION_ENABLED": "vision_enabled",
}

_TRUE_VALUES = {"1", "true", "yes", "on"}


def resume_from_environment(value: str | None) -> bool:
    """Parse BOLT_RESUME without treating arbitrary non-empty values as true."""
    return value is not None and value.strip().casefold() in _TRUE_VALUES


def resolve_resume(cli_value: bool | None, settings: Settings) -> Settings:
    """Apply explicit CLI intent over the already parsed environment policy."""
    return settings if cli_value is None else settings.model_copy(update={"resume": cli_value})

def load_settings() -> Settings:
    """Load defaults, user config, local config, then environment values."""
    values: dict[str, Any] = {}
    config_name = os.getenv("BOLT_CONFIG") or os.getenv("BOLTSPY_CONFIG")
    user_config = Path(config_name) if config_name else Path.home() / ".config" / "bolt" / "config.toml"
    values.update(_read_toml(user_config))
    if not config_name:
        values = {**_read_toml(Path.home() / ".config" / "boltpy" / "config.toml"), **values}
    values.update(_read_toml(Path.cwd() / "boltpy.toml"))
    for env_name, field_name in _ENV_FIELDS.items():
        if value := os.getenv(env_name):
            values[field_name] = [item.strip() for item in value.split(",") if item.strip()] if field_name == "models" else value
    settings = Settings(**values, resume=resume_from_environment(os.getenv("BOLT_RESUME")))
    settings.workspace = settings.workspace.expanduser().resolve()
    session_marker = settings.workspace / ".bolt" / "sessions" / "latest.json"
    explicitly_configured = "permission_mode" in values
    settings.first_launch = not session_marker.is_file() and not explicitly_configured
    return settings

def require_api_key(settings: Settings) -> str:
    """Return the key or raise an actionable configuration error."""
    if settings.api_key:
        return settings.api_key
    raise RuntimeError("No API key configured. Set OPENAI_API_KEY or api_key in boltpy.toml. For local servers, set api_key to any non-empty value.")
