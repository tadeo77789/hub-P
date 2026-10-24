from typing import Protocol

from paula_hub.domain.messages import Event, Order


class MessageHandler(Protocol):
    """Entry point the inbound adapters call into."""

    def handle_order(self, order: Order) -> None: ...

    def handle_event(self, event: Event) -> None: ...
