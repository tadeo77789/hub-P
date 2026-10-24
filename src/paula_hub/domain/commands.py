"""Whitelist of commands the agent may run.

The agent keeps its own copy of this list and refuses anything else, so a
command only works when both sides know it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    destructive: bool = False


def _schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = properties or {}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


WHITELIST: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec(
            name="open_app",
            description=(
                "Open an application on the user's PC. `app` is the app's common name, "
                "for example 'navegador', 'spotify' or 'calculadora'. The PC agent only "
                "opens apps from its configured list and reports an error otherwise."
            ),
            input_schema=_schema({"app": {"type": "string"}}),
        ),
        CommandSpec(
            name="system_status",
            description=(
                "Read the PC status: CPU, memory, disk, battery and uptime. Use it when the "
                "user asks how the computer is doing."
            ),
            input_schema=_schema(),
        ),
        CommandSpec(
            name="shutdown_pc",
            description=(
                "Shut down the user's PC after a 60 second grace period. Destructive: the "
                "user is always asked to confirm before it runs."
            ),
            input_schema=_schema(),
            destructive=True,
        ),
    )
}


def get_command(name: str) -> CommandSpec | None:
    return WHITELIST.get(name)
