"""HMAC-SHA256 signatures for every message between hub and agent.

Mirrored in pc-agent (paula_agent/messaging/signing.py).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque
from pathlib import Path

SIGNATURE_HEADER = "x-paula-signature"
SENT_AT_HEADER = "x-paula-sent-at"

# Actions may wait in the queue while the PC is off, so old messages stay valid.
DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600


class InvalidSignature(Exception):
    pass


def _digest(secret: str, sent_at: str, body: bytes) -> str:
    return hmac.new(secret.encode(), sent_at.encode() + b"." + body, hashlib.sha256).hexdigest()


def sign(secret: str, body: bytes, *, now: float | None = None) -> dict[str, str]:
    """Return the headers to attach to a message with this body."""
    if not secret:
        raise ValueError("AGENT_SHARED_SECRET is empty")
    sent_at = str(int(now if now is not None else time.time()))
    return {SIGNATURE_HEADER: _digest(secret, sent_at, body), SENT_AT_HEADER: sent_at}


def verify(
    secret: str,
    body: bytes,
    headers: dict[str, object] | None,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> None:
    headers = headers or {}
    signature = headers.get(SIGNATURE_HEADER)
    sent_at = headers.get(SENT_AT_HEADER)
    if not isinstance(signature, str) or not isinstance(sent_at, str):
        raise InvalidSignature("missing signature headers")
    if not hmac.compare_digest(signature, _digest(secret, sent_at, body)):
        raise InvalidSignature("signature mismatch")
    try:
        age = (now if now is not None else time.time()) - int(sent_at)
    except ValueError as exc:
        raise InvalidSignature("bad timestamp") from exc
    if age > max_age_seconds or age < -300:
        raise InvalidSignature("message too old or from the future")


class SeenIds:
    """Recent message ids, so a captured signed message cannot be replayed.

    The signature window is long (queued actions), so the id is what makes a
    message single-use. With a path, the ids survive restarts.
    """

    def __init__(self, limit: int = 2000, path: Path | None = None) -> None:
        self._limit = limit
        self._path = path
        self._order: deque[str] = deque()
        self._ids: set[str] = set()
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                self._remember(line.strip())

    def add(self, message_id: str | None) -> bool:
        """Record the id; False if it was already seen."""
        if not message_id:
            return True
        if message_id in self._ids:
            return False
        self._remember(message_id)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(self._order) + "\n", encoding="utf-8")
        return True

    def _remember(self, message_id: str) -> None:
        if not message_id or message_id in self._ids:
            return
        self._order.append(message_id)
        self._ids.add(message_id)
        while len(self._order) > self._limit:
            self._ids.discard(self._order.popleft())
