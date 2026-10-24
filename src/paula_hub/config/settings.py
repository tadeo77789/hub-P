"""Settings read from environment variables (and `.env` in the working directory)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from paula_hub.adapters.outbound.claude.assistant import DEFAULT_MODEL


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    rabbitmq_url: str
    agent_shared_secret: str
    claude_model: str
    claude_effort: str
    alexa_notify_url: str
    long_task_seconds: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        secret = os.environ.get("AGENT_SHARED_SECRET", "")
        if len(secret) < 32:
            raise SettingsError("AGENT_SHARED_SECRET must be at least 32 characters")
        return cls(
            rabbitmq_url=os.environ.get("RABBITMQ_URL", "amqp://paula:paula@localhost:5672/"),
            agent_shared_secret=secret,
            claude_model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
            claude_effort=os.environ.get("CLAUDE_EFFORT", "low"),
            alexa_notify_url=os.environ.get("ALEXA_NOTIFY_URL", ""),
            long_task_seconds=float(os.environ.get("LONG_TASK_SECONDS", "30")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
