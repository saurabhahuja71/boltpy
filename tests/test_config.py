from boltpy.config import Settings, load_settings
def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "local-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "local")
    settings = load_settings()
    assert settings.model == "local-model"
    assert settings.base_url == "http://localhost:1234/v1"
    assert settings.api_key == "local"
def test_settings_defaults():
    assert Settings().model == "gpt-4o-mini"
