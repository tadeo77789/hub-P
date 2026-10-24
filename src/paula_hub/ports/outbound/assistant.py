from collections.abc import Callable, Sequence
from typing import Protocol

from paula_hub.domain.conversation import AssistantTurn, ToolResult


class AssistantError(Exception):
    """The language model could not produce a turn."""


class AssistantPort(Protocol):
    """Language model that keeps one conversation per session.

    Every tool call of a turn must be answered in the next `send`, before or
    together with new user text. With `on_text`, reply text is also handed over in
    pieces as it is generated (for speaking before the turn is complete). `context`
    holds facts recalled from long-term memory and `references` passages from the
    user's documents, both for this turn only; they are not kept in the history.
    """

    def send(
        self,
        session_id: str,
        *,
        text: str | None = None,
        results: Sequence[ToolResult] = (),
        on_text: Callable[[str], None] | None = None,
        context: Sequence[str] = (),
        references: Sequence[str] = (),
    ) -> AssistantTurn: ...

    def reset(self, session_id: str) -> None: ...
