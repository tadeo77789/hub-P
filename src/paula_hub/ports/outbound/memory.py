from typing import Protocol

from paula_hub.domain.memory import MemoryFact


class MemoryUnavailable(Exception):
    """The memory store or its embedding model could not be reached."""


class MemoryPort(Protocol):
    """Facts about the user, searched by meaning rather than by exact words."""

    def remember(self, text: str) -> MemoryFact:
        """Save a fact; a near-duplicate replaces the older wording."""
        ...

    def recall(self, query: str, limit: int = 5) -> list[MemoryFact]:
        """Facts related to `query`, most related first."""
        ...

    def forget(self, about: str) -> list[MemoryFact]:
        """Delete the facts that match `about` and return them."""
        ...

    def all(self) -> list[MemoryFact]: ...
