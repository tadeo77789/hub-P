"""RabbitMQ names shared by hub and agent. Mirrored in pc-agent (paula_agent/messaging/topology.py).

agent ──order──▶ hub.orders     hub ──result──▶ agent.results
agent ──event──▶ hub.events     hub ──action──▶ agent.actions
"""

EXCHANGE = "paula"

ORDER_KEY = "order"
EVENT_KEY = "event"
RESULT_KEY = "result"
ACTION_KEY = "action"

QUEUES = {
    "hub.orders": ORDER_KEY,
    "hub.events": EVENT_KEY,
    "agent.results": RESULT_KEY,
    "agent.actions": ACTION_KEY,
}


def declare(channel) -> None:
    """Idempotently declare the exchange, queues and bindings (pika channel)."""
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    for queue, key in QUEUES.items():
        channel.queue_declare(queue=queue, durable=True)
        channel.queue_bind(queue=queue, exchange=EXCHANGE, routing_key=key)
