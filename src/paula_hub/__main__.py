"""Run the hub: python -m paula_hub"""

from __future__ import annotations

import logging
import signal
import sys
import time

from pika.exceptions import AMQPError

from paula_hub.adapters.outbound.alexa.notifier import AlexaNotifier, LogNotifier
from paula_hub.adapters.outbound.claude.assistant import ClaudeAssistant
from paula_hub.adapters.rabbitmq import RabbitMqBroker
from paula_hub.application.assistant_service import AssistantService
from paula_hub.config.settings import Settings, SettingsError

log = logging.getLogger("paula_hub")

RECONNECT_SECONDS = 5


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    broker = RabbitMqBroker(settings.rabbitmq_url, settings.agent_shared_secret)
    notifier = (
        AlexaNotifier(settings.alexa_notify_url, settings.agent_shared_secret)
        if settings.alexa_notify_url
        else LogNotifier()
    )
    service = AssistantService(
        ClaudeAssistant(model=settings.claude_model, effort=settings.claude_effort),
        broker,
        notifier,
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
