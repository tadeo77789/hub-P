import pytest

from paula_hub.config import settings as settings_module
from paula_hub.config.settings import Settings, SettingsError


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(settings_module, "load_dotenv", lambda: None)
    for name in (
        "AGENT_SHARED_SECRET",
        "CLAUDE_MODEL",
        "ALEXA_NOTIFY_URL",
        "ALEXA_NOTIFY_SECRET",
        "RABBITMQ_URL",
        "LOG_LEVEL",
        "LONG_TASK_SECONDS",
    ):
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


@pytest.mark.parametrize(
    ("name", "value"),
    [("LONG_TASK_SECONDS", "abc"), ("LOG_LEVEL", "LOUD")],
)
def test_invalid_values_are_settings_errors(monkeypatch, name, value):
    monkeypatch.setenv("AGENT_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv(name, value)

    with pytest.raises(SettingsError):
        Settings.from_env()


def test_alexa_needs_its_own_secret(monkeypatch):
    monkeypatch.setenv("AGENT_SHARED_SECRET", "x" * 32)
    monkeypatch.setenv("ALEXA_NOTIFY_URL", "https://lambda.example")

    with pytest.raises(SettingsError):
        Settings.from_env()
    monkeypatch.setenv("ALEXA_NOTIFY_SECRET", "x" * 32)
    with pytest.raises(SettingsError):
        Settings.from_env()
    monkeypatch.setenv("ALEXA_NOTIFY_SECRET", "y" * 32)
    assert Settings.from_env().alexa_notify_secret == "y" * 32
