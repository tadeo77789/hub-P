"""Run the hub: python -m paula_hub"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from pika.exceptions import AMQPError

from paula_hub.adapters.outbound.alexa.notifier import AlexaNotifier, LogNotifier
from paula_hub.adapters.outbound.memory.store import OllamaEmbedder, SqliteMemory
from paula_hub.adapters.outbound.ollama.assistant import OllamaAssistant
from paula_hub.adapters.rabbitmq import RabbitMqBroker
from paula_hub.application.assistant_service import AssistantService
from paula_hub.config.settings import Settings, SettingsError, log_dir, setup_logging
from paula_hub.ports.outbound.memory import MemoryUnavailable

log = logging.getLogger("paula_hub")

RECONNECT_SECONDS = 5


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        # pythonw has no console: leave the error where it can be found.
        log_dir().mkdir(parents=True, exist_ok=True)
        (log_dir() / "hub-config-error.txt").write_text(str(exc), encoding="utf-8")
        if sys.stderr is not None:
            print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level, "hub")

    broker = RabbitMqBroker(
        settings.rabbitmq_url,
        settings.agent_shared_secret,
        seen_path=log_dir().parent / "hub_seen_ids.txt",
    )
    notifier = (
        AlexaNotifier(settings.alexa_notify_url, settings.alexa_notify_secret)
        if settings.alexa_notify_url
        else LogNotifier()
    )
    memory = None
    if settings.memory_embed_model.lower() != "off":

        def embedder(timeout: float) -> OllamaEmbedder:
            return OllamaEmbedder(
                settings.ollama_url,
                settings.memory_embed_model,
                timeout=timeout,
                keep_alive=settings.ollama_keep_alive,
            )

        memory = SqliteMemory(
            log_dir().parent / "memory.sqlite3",
            embedder(20.0),  # remember/forget/warm-up may load the model
            recall_embed=embedder(3.0),  # every answer waits for this one
        )

        def warm_up() -> None:
            try:
                memory.warm_up()
            except MemoryUnavailable as exc:
                log.warning("Memory model not ready: %s", exc)

        threading.Thread(target=warm_up, name="memory-warm-up", daemon=True).start()
    service = AssistantService(
        OllamaAssistant(
            url=settings.ollama_url,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout,
            keep_alive=settings.ollama_keep_alive,
        ),
        broker,
        notifier,
        memory=memory,
        long_task_seconds=settings.long_task_seconds,
    )

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        broker.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        try:
            broker.serve(service)
        except AMQPError as exc:
            log.warning("RabbitMQ unavailable (%s); retrying in %ss", exc, RECONNECT_SECONDS)
            time.sleep(RECONNECT_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
