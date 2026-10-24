"""Message contracts exchanged between hub, pc-agent and Alexa.

Order, Result and Alert follow notas/03-mensajes-y-stack.md. Action and Event
carry whitelisted commands to the agent and their outcome back to the hub.
Any change here must be mirrored in pc-agent (paula_agent/messaging/messages.py).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Source(str, Enum):
    VOICE = "voice"
    CHAT = "chat"
    ALEXA = "alexa"
    HOTKEY = "hotkey"


class Intent(str, Enum):
    OPEN_APP = "open_app"
    SYSTEM_STATUS = "system_status"
    WAKE_PC = "wake_pc"
    CONVERSATION = "conversation"
    CONFIRM = "confirm"


class Status(str, Enum):
    OK = "ok"
    ERROR = "error"
    PENDING = "pending"
    QUESTION = "question"


class Channel(str, Enum):
    PC = "pc"
    ALEXA = "alexa"
    CHAT = "chat"


class RobotState(str, Enum):
    SLEEPING = "sleeping"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    QUESTION = "question"
    ANGRY = "angry"


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _enum_values(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in data.items()}


@dataclass(frozen=True)
class Order:
    """Request coming from a channel (voice, chat, hotkey or Alexa)."""

    source: Source
    intent: Intent
    payload: dict[str, Any]
    id: str = field(default_factory=new_id)
    timestamp: str = field(default_factory=now_iso)
    requires_confirmation: bool = False

    @property
    def text(self) -> str:
        return str(self.payload.get("text", "")).strip()

    def to_dict(self) -> dict[str, Any]:
        return _enum_values(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Order:
        return cls(
            id=data["id"],
            source=Source(data["source"]),
            timestamp=data["timestamp"],
            intent=Intent(data["intent"]),
            payload=dict(data.get("payload") or {}),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
        )


@dataclass(frozen=True)
class Result:
    """Reply to an order. `options` is only set when status is QUESTION."""

    id: str
    status: Status
    response_text: str
    speak: bool
    channel: Channel
    robot_state: RobotState
    options: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = _enum_values(asdict(self))
        if self.options is None:
            data.pop("options")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result:
        return cls(
            id=data["id"],
            status=Status(data["status"]),
            response_text=data["response_text"],
            speak=bool(data["speak"]),
            channel=Channel(data["channel"]),
            robot_state=RobotState(data["robot_state"]),
            options=data.get("options"),
        )


@dataclass(frozen=True)
class Alert:
    title: str
    message: str
    target: str = "alexa"
    type: str = "alert"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Action:
    """Whitelisted command the hub asks the agent to run."""

    order_id: str
    command: str
    args: dict[str, Any]
    confirmed: bool = False
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        return cls(
            id=data["id"],
            order_id=data["order_id"],
            command=data["command"],
            args=dict(data.get("args") or {}),
            confirmed=bool(data.get("confirmed", False)),
        )


@dataclass(frozen=True)
class Event:
    """Outcome of an Action, reported by the agent."""

    action_id: str
    status: Status
    output: str
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return _enum_values(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            action_id=data["action_id"],
            status=Status(data["status"]),
            output=str(data.get("output", "")),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
        )
