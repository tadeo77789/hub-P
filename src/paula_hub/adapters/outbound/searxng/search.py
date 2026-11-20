"""WebSearchPort backed by a local SearXNG (deploy/docker-compose.yml).

SearXNG queries several search engines (Google, Bing, DuckDuckGo...) and returns the
merged results as JSON, with no account or API key. It runs on localhost only.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from paula_hub.domain.web_search import WebResult
from paula_hub.ports.outbound.web_search import WebSearchUnavailable

log = logging.getLogger(__name__)

# 127.0.0.1, not localhost: the port binds IPv4 only, and on Windows "localhost" tries
# ::1 first, which costs about 2 s per search before falling back.
DEFAULT_URL = "http://127.0.0.1:8888"
# Enough for the model to answer from without crowding the context window.
MAX_SNIPPET_CHARS = 300
MAX_QUERY_CHARS = 200

Get = Callable[[str, float], Any]


def http_get(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _web_url(raw: Any) -> str | None:
    url = str(raw or "")
    try:
        parts = urlsplit(url)
    except ValueError:  # e.g. "http://[::1"
        return None
    return url if parts.scheme in ("http", "https") and parts.hostname else None


class SearxngSearch:
    def __init__(
        self, url: str = DEFAULT_URL, *, timeout: float = 8.0, get: Get = http_get
    ) -> None:
        self._endpoint = url.rstrip("/") + "/search"
        self._timeout = timeout
        self._get = get

    def search(self, query: str, limit: int = 5) -> list[WebResult]:
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query:
            raise ValueError("the search query is empty")
        params = urllib.parse.urlencode({"q": query, "format": "json", "safesearch": 1})
        try:
            data = self._get(f"{self._endpoint}?{params}", self._timeout)
        # OSError: URLError, timeouts, HTTP 403 (json off). ValueError: bad JSON.
        # HTTPException: a truncated or garbled answer.
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise WebSearchUnavailable(str(exc) or type(exc).__name__) from exc
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise WebSearchUnavailable("unexpected answer from SearXNG")
        results = []
        for item in items:
            url = _web_url(item.get("url")) if isinstance(item, dict) else None
            if url is None:
                continue
            results.append(
                WebResult(
                    title=" ".join(str(item.get("title") or "").split()),
                    url=url,
                    snippet=" ".join(str(item.get("content") or "").split())[:MAX_SNIPPET_CHARS],
                )
            )
            if len(results) >= limit:
                break
        # The query itself stays out of the INFO log: it is the user's own question.
        log.info("Web search: %d results", len(results))
        log.debug("Web search query: %r", query)
        return results
