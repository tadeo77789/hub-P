"""Round trip through a real RabbitMQ. Skipped when no broker is reachable.

Start one with: docker compose -f deploy/docker-compose.yml up -d
"""

import json
import os
import threading
import time

import pika
import pytest

from paula_hub.adapters import topology
from paula_hub.adapters.rabbitmq import RabbitMqBroker
from paula_hub.adapters.signing import sign, verify
from paula_hub.domain.messages import (
    Channel,
    Event,
    Intent,
    Order,
    Result,
    RobotState,
    Source,
    Status,
)

URL = os.environ.get("RABBITMQ_URL", "amqp://paula:paula@localhost:5672/")
SECRET = "integration-secret"


def broker_available() -> bool:
    try:
        pika.BlockingConnection(pika.URLParameters(URL)).close()
        return True
    except pika.exceptions.AMQPError:
        return False


pytestmark = pytest.mark.skipif(not broker_available(), reason="RabbitMQ not reachable")


class EchoHandler:
    def __init__(self, broker: RabbitMqBroker) -> None:
        self.broker = broker
        self.events: list[Event] = []

    def handle_order(self, order: Order) -> None:
        self.broker.reply(
            Result(
                order.id, Status.OK, f"eco: {order.text}", False, Channel.CHAT, RobotState.SLEEPING
            )
        )

    def handle_event(self, event: Event) -> None:
        self.events.append(event)


def publish(channel, key: str, data: dict, secret: str | None = SECRET) -> None:
    body = json.dumps(data).encode()
    headers = sign(secret, body) if secret else None
    channel.basic_publish(topology.EXCHANGE, key, body, pika.BasicProperties(headers=headers))


def test_order_gets_signed_result_and_unsigned_is_dropped():
    broker = RabbitMqBroker(URL, SECRET)
    handler = EchoHandler(broker)
    thread = threading.Thread(target=broker.serve, args=(handler,), daemon=True)
    thread.start()

    connection = pika.BlockingConnection(pika.URLParameters(URL))
    channel = connection.channel()
    topology.declare(channel)
    channel.queue_purge("agent.results")
    time.sleep(0.5)

    order = Order(source=Source.CHAT, intent=Intent.CONVERSATION, payload={"text": "hola"})
    publish(channel, topology.ORDER_KEY, {"unsigned": True}, secret=None)
    publish(channel, topology.ORDER_KEY, order.to_dict())
    publish(channel, topology.EVENT_KEY, Event("a1", Status.OK, "done").to_dict())

    deadline = time.monotonic() + 5
    received = None
    while time.monotonic() < deadline and received is None:
        method, properties, body = channel.basic_get("agent.results", auto_ack=True)
        if method is not None:
            verify(SECRET, body, properties.headers)
            received = Result.from_dict(json.loads(body))
        time.sleep(0.05)

    broker.stop()
    thread.join(timeout=5)
    connection.close()

    assert received is not None and received.response_text == "eco: hola"
    assert [e.action_id for e in handler.events] == ["a1"]
