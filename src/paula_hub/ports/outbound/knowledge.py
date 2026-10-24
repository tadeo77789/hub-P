from typing import Protocol

from paula_hub.domain.knowledge import Passage


class KnowledgePort(Protocol):
    """Passages from the user's documents, searched by meaning."""

    def search(self, query: str, limit: int = 3) -> list[Passage]: ...

    def learn(self, title: str, text: str) -> str:
        """Save a note and index it; returns the note's file name."""
        ...
