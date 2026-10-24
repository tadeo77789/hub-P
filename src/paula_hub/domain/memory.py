"""Long-term memory: short facts about the user that Paula keeps between conversations.

Memory tools run inside the hub (they never reach the PC agent), so they live apart
from the command whitelist.
"""

from __future__ import annotations

from dataclasses import dataclass

from paula_hub.domain.commands import CommandSpec, _schema


@dataclass(frozen=True)
class MemoryFact:
    id: str
    text: str
    created_at: str  # ISO-8601


MEMORY_TOOLS: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec(
            name="remember",
            description=(
                "Save one lasting fact about the user in long-term memory: preferences, "
                "people and pets, important dates, plans, how they like things done. "
                "`fact` is one short self-contained sentence in Spanish about the user, "
                "for example 'A Ola le gusta el rock de los 80'. Use it when the user asks "
                "you to remember something or shares something worth knowing later. Do not "
                "save small talk, questions or things that only matter right now."
            ),
            input_schema=_schema({"fact": {"type": "string"}}),
        ),
        CommandSpec(
            name="forget",
            description=(
                "Delete what long-term memory holds about a topic, when the user asks you "
                "to forget it or says a saved fact is wrong. `about` describes the fact."
            ),
            input_schema=_schema({"about": {"type": "string"}}),
        ),
        CommandSpec(
            name="list_memories",
            description="List everything in long-term memory, when the user asks what you know about them.",
            input_schema=_schema(),
        ),
    )
}
