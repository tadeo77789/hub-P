"""Web search: lets Paula look up recent or unknown things on the internet.

The `search_web` tool runs inside the hub, like the memory tools; the PC agent is
never involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from paula_hub.domain.commands import CommandSpec, tool_schema


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


WEB_SEARCH_TOOLS: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec(
            name="search_web",
            description=(
                "Search the internet. Use it for anything recent or that you are not sure "
                "about: news, prices, weather, sports results, release dates, people and "
                "events after your training. `query` is a short search, a few words, in the "
                "language that will find the best results."
            ),
            input_schema=tool_schema({"query": {"type": "string"}}),
        ),
    )
}
