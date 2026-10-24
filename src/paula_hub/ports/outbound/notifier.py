from typing import Protocol

from paula_hub.domain.messages import Alert


class NotifierPort(Protocol):
    """Sends alerts outside the PC (Alexa)."""

    def notify(self, alert: Alert) -> None: ...
