"""Knowledge base: documents the user gives Paula (notes, guides, PDFs) to answer from.

Unlike long-term memory (short facts about the user), these are reference passages.
The `learn` tool runs inside the hub, like the memory tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from paula_hub.domain.commands import CommandSpec, tool_schema


@dataclass(frozen=True)
class Passage:
    source: str  # file name inside the knowledge folder
    text: str


KNOWLEDGE_TOOLS: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec(
            name="learn",
            description=(
                "Save a note in the user's knowledge base so you can answer from it later. "
                "Use it when the user asks you to learn, study or keep some information "
                "that is not a fact about themself (for example how something works, a "
                "procedure, a definition). `title` is a few words; `text` is the content in "
                "Spanish, complete and self-contained."
            ),
            input_schema=tool_schema({"title": {"type": "string"}, "text": {"type": "string"}}),
        ),
    )
}
