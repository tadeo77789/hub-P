"""NotifierPort that forwards alerts to the Alexa Lambda (see alexa-skill/)."""

from __future__ import annotations

import json
import logging
import urllib.request

from paula_hub.adapters.signing import sign
from paula_hub.domain.messages import Alert

log = logging.getLogger(__name__)


class AlexaNotifier:
    def __init__(self, url: str, secret: str, *, timeout: float = 5.0) -> None:
        self._url = url
        self._secret = secret
        self._timeout = timeout

    def notify(self, alert: Alert) -> None:
        body = json.dumps(alert.to_dict(), ensure_ascii=False).encode()
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", **sign(self._secret, body)},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                log.info("Alexa alert sent (%s)", response.status)
        except OSError as exc:  # URLError, timeouts, dropped connections
            # Alerts are best effort; never break the conversation over them.
            log.warning("Could not send Alexa alert: %s", exc)


class LogNotifier:
    """Used when ALEXA_NOTIFY_URL is not configured."""

    def notify(self, alert: Alert) -> None:
        log.info("Alert (Alexa not configured): %s - %s", alert.title, alert.message)
