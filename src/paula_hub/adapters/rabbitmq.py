"""RabbitMQ adapter: consumes orders and events, publishes results and actions.

Everything runs on one thread: the service is called from the consumer
callback and publishes on the same channel.
"""

from __future__ import annotations

import json
import logging

import pika
from pika.adapters.blocking_connection import BlockingChannel

from paula_hub.adapters import topology
from paula_hub.adapters.signing import InvalidSignature, sign, verify
from paula_hub.domain.messages import Action, Event, Order, Result
from paula_hub.ports.inbound.message_handler import MessageHandler

log = logging.getLogger(__name__)


class RabbitMqBroker:
    """Implements AgentGatewayPort and drives a MessageHandler."""

    def __init__(self, url: str, secret: str) -> None:
        self._params = pika.URLParameters(url)
        # Claude calls block the consumer; keep the heartbeat well above them.
        self._params.heartbeat = 600
        self._secret = secret
        self._connection: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    # AgentGatewayPort

    def reply(self, result: Result) -> None:
        self._publish(topology.RESULT_KEY, result.to_dict())

    def dispatch(self, action: Action) -> None:
        self._publish(topology.ACTION_KEY, action.to_dict())

    # Consumer

    def serve(self, handler: MessageHandler) -> None:
        """Block consuming until the connection drops or stop() is called."""
        self._connection = pika.BlockingConnection(self._params)
        self._channel = self._connection.channel()
        topology.declare(self._channel)
        self._channel.basic_qos(prefetch_count=1)
        self._channel.basic_consume("hub.orders", self._on(Order.from_dict, handler.handle_order))
        self._channel.basic_consume("hub.events", self._on(Event.from_dict, handler.handle_event))
        log.info("Hub consuming from RabbitMQ")
        try:
            self._channel.start_consuming()
        finally:
            if self._connection.is_open:
                self._connection.close()
            self._connection = self._channel = None

    def stop(self) -> None:
        if self._connection is not None and self._channel is not None:
            self._connection.add_callback_threadsafe(self._channel.stop_consuming)

    def _publish(self, key: str, data: dict) -> None:
        if self._channel is None:
            raise RuntimeError("RabbitMqBroker is not connected")
        body = json.dumps(data, ensure_ascii=False).encode()
        self._channel.basic_publish(
            exchange=topology.EXCHANGE,
            routing_key=key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                headers=sign(self._secret, body),
            ),
        )

    def _on(self, parse, callback):
        def on_message(channel, method, properties, body: bytes) -> None:
            channel.basic_ack(method.delivery_tag)
            try:
                verify(self._secret, body, properties.headers)
                message = parse(json.loads(body))
            except (InvalidSignature, ValueError, KeyError) as exc:
                log.warning("Dropping invalid message on %s: %s", method.routing_key, exc)
                return
            try:
                callback(message)
            except Exception:
                log.exception("Handler failed for %s", method.routing_key)

        return on_message
