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
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    models: list[str] = Field(default_factory=list)
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    system_prompt: str = "You are Boltpy, a helpful terminal coding assistant."
    permission_mode: Literal["ask", "allow", "plan"] = "ask"
    theme: str = "light"

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
    "OPENAI_PROVIDER": "provider",
    "BOLTPY_PROVIDER": "provider",
    "BOLTPY_MODELS": "models",
    "BOLTPY_PERMISSION_MODE": "permission_mode",
    "BOLTPY_THEME": "theme",
}

def load_settings() -> Settings:
    """Load defaults, user config, local config, then environment values."""
    values: dict[str, Any] = {}
    values.update(_read_toml(Path.home() / ".config" / "boltpy" / "config.toml"))
    values.update(_read_toml(Path.cwd() / "boltpy.toml"))
    for env_name, field_name in _ENV_FIELDS.items():
        if value := os.getenv(env_name):
            values[field_name] = [item.strip() for item in value.split(",") if item.strip()] if field_name == "models" else value
    return Settings(**values)

def require_api_key(settings: Settings) -> str:
    """Return the key or raise an actionable configuration error."""
    if settings.api_key:
        return settings.api_key
    raise RuntimeError("No API key configured. Set OPENAI_API_KEY or api_key in boltpy.toml. For local servers, set api_key to any non-empty value.")
