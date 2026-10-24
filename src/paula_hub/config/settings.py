"""Settings read from environment variables (and `.env` in the working directory)."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from paula_hub.adapters.outbound.ollama.assistant import DEFAULT_MODEL, DEFAULT_URL

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class SettingsError(Exception):
    pass


def log_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PaulaPort" / "logs"


def setup_logging(level: str, name: str) -> None:
    """Log to a rotating file (pythonw at logon has no console) and to stderr if present."""
    log_dir().mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_dir() / f"{name}.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


@dataclass(frozen=True)
class Settings:
    rabbitmq_url: str
    agent_shared_secret: str
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    ollama_keep_alive: str
    alexa_notify_url: str
    alexa_notify_secret: str
    long_task_seconds: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        secret = os.environ.get("AGENT_SHARED_SECRET", "")
        if len(secret) < 32:
            raise SettingsError("AGENT_SHARED_SECRET must be at least 32 characters")

        alexa_url = os.environ.get("ALEXA_NOTIFY_URL", "")
        alexa_secret = os.environ.get("ALEXA_NOTIFY_SECRET", "")
        if alexa_url and len(alexa_secret) < 32:
            raise SettingsError("ALEXA_NOTIFY_SECRET (32+ chars) is required with ALEXA_NOTIFY_URL")
        if alexa_url and alexa_secret == secret:
            raise SettingsError("ALEXA_NOTIFY_SECRET must differ from AGENT_SHARED_SECRET")

        log_level = (os.environ.get("LOG_LEVEL") or "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise SettingsError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
        try:
            long_task_seconds = float(os.environ.get("LONG_TASK_SECONDS") or 30)
            ollama_timeout = float(os.environ.get("OLLAMA_TIMEOUT") or 60)
        except ValueError as exc:
            raise SettingsError("LONG_TASK_SECONDS and OLLAMA_TIMEOUT must be numbers") from exc

        return cls(
            rabbitmq_url=os.environ.get("RABBITMQ_URL") or "amqp://paula:paula@localhost:5672/",
            agent_shared_secret=secret,
            ollama_url=os.environ.get("OLLAMA_URL") or DEFAULT_URL,
            ollama_model=os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL,
            ollama_timeout=ollama_timeout,
            ollama_keep_alive=os.environ.get("OLLAMA_KEEP_ALIVE") or "30m",
            alexa_notify_url=alexa_url,
            alexa_notify_secret=alexa_secret,
            long_task_seconds=long_task_seconds,
            log_level=log_level,
        )
