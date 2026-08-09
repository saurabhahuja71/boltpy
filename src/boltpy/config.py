"""Configuration loading for Boltpy."""
from __future__ import annotations
import os
import tomllib
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class Settings(BaseModel):
    """Runtime settings for OpenAI-compatible APIs."""
    model_config = ConfigDict(extra="ignore")
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    system_prompt: str = "You are Boltpy, a helpful terminal coding assistant."

def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as file:
        value = tomllib.load(file)
    return value if isinstance(value, dict) else {}

def load_settings() -> Settings:
    """Load defaults, user config, local config, then environment values."""
    values: dict[str, Any] = {}
    values.update(_read_toml(Path.home() / ".config" / "boltpy" / "config.toml"))
    values.update(_read_toml(Path.cwd() / "boltpy.toml"))
    for env_name, field_name in {"OPENAI_API_KEY": "api_key", "OPENAI_BASE_URL": "base_url", "OPENAI_MODEL": "model"}.items():
        if value := os.getenv(env_name):
            values[field_name] = value
    return Settings(**values)

def require_api_key(settings: Settings) -> str:
    """Return the key or raise an actionable configuration error."""
    if settings.api_key:
        return settings.api_key
    raise RuntimeError("No API key configured. Set OPENAI_API_KEY or api_key in boltpy.toml. For local servers, set api_key to any non-empty value.")
