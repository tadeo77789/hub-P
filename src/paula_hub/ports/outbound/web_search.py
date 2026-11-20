from typing import Protocol

from paula_hub.domain.web_search import WebResult


class WebSearchUnavailable(Exception):
    """The search engine could not be reached or answered with an error."""


class WebSearchPort(Protocol):
    def search(self, query: str, limit: int = 5) -> list[WebResult]: ...
