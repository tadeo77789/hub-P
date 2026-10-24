from typing import Protocol

from paula_hub.domain.memory import MemoryFact


class MemoryUnavailable(Exception):
    """The memory store or its embedding model could not be reached."""


class AmbiguousForget(Exception):
    """Too many facts match a forget request; nothing was deleted."""

    def __init__(self, candidates: list[MemoryFact]) -> None:
        super().__init__(f"{len(candidates)} facts match")
        self.candidates = candidates


class MemoryPort(Protocol):
    """Facts about the user, searched by meaning rather than by exact words."""

    def remember(self, text: str) -> MemoryFact:
        """Save a fact; a near-duplicate replaces the older wording."""
        ...

    def recall(self, query: str, limit: int = 5) -> list[MemoryFact]:
        """Facts related to `query`, most related first."""
        ...

    def forget(self, about: str) -> list[MemoryFact]:
        """Delete the facts that match `about` and return them.

        Raises AmbiguousForget instead of deleting when too many facts match.
        """
        ...

    def all(self) -> list[MemoryFact]: ...
