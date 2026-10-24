import pytest

from paula_hub.config import settings as settings_module
from paula_hub.config.settings import Settings, SettingsError


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(settings_module, "load_dotenv", lambda: None)
    for name in ("AGENT_SHARED_SECRET", "CLAUDE_MODEL", "ALEXA_NOTIFY_URL", "RABBITMQ_URL"):
        monkeypatch.delenv(name, raising=False)


def test_short_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", "short")

    with pytest.raises(SettingsError):
        Settings.from_env()


def test_defaults(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", "x" * 32)

    settings = Settings.from_env()

    assert settings.claude_model == "claude-opus-5-5"
    assert settings.claude_effort == "low"
    assert settings.alexa_notify_url == ""
    assert settings.rabbitmq_url.startswith("amqp://")


def test_empty_values_use_defaults(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("CLAUDE_MODEL", "")

    assert Settings.from_env().claude_model == "claude-opus-5-5"
