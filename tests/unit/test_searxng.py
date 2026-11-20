import http.client
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from paula_hub.adapters.outbound.searxng.search import MAX_SNIPPET_CHARS, SearxngSearch
from paula_hub.domain.web_search import WebResult
from paula_hub.ports.outbound.web_search import WebSearchUnavailable


def fake_get(answer):
    calls = []

    def get(url, timeout):
        calls.append((url, timeout))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return get, calls


def test_query_goes_to_the_json_api():
    get, calls = fake_get({"results": []})

    SearxngSearch("http://localhost:8888/", get=get).search("  clima   en Bogotá ")

    url, timeout = calls[0]
    parts = urlsplit(url)
    assert parts.path == "/search"
    assert parse_qs(parts.query) == {
        "q": ["clima en Bogotá"],
        "format": ["json"],
        "safesearch": ["1"],
    }
    assert timeout == 8.0


def test_results_are_cleaned_and_limited():
    get, _ = fake_get(
        {
            "results": [
                {"title": " Clima\n hoy ", "url": "https://a.com/x", "content": "Soleado " * 100},
                {"title": "Sin esquema", "url": "javascript:alert(1)", "content": "x"},
                "not a result",
                {"title": "B", "url": "http://b.com", "content": None},
                {"title": "C", "url": "https://c.com", "content": "c"},
            ]
        }
    )

    results = SearxngSearch(get=get).search("clima", limit=2)

    assert [r.url for r in results] == ["https://a.com/x", "http://b.com"]
    assert results[0].title == "Clima hoy"
    assert len(results[0].snippet) == MAX_SNIPPET_CHARS
    assert results[1] == WebResult("B", "http://b.com", "")


@pytest.mark.parametrize(
    "answer",
    [
        urllib.error.URLError("connection refused"),
        TimeoutError("timed out"),
        ValueError("bad json"),
    ],
)
def test_failures_become_unavailable(answer):
    get, _ = fake_get(answer)

    with pytest.raises(WebSearchUnavailable):
        SearxngSearch(get=get).search("clima")


def test_unexpected_answer_is_unavailable():
    get, _ = fake_get(["not", "a", "dict"])

    with pytest.raises(WebSearchUnavailable):
        SearxngSearch(get=get).search("clima")


def test_empty_query_is_rejected():
    get, calls = fake_get({"results": []})

    with pytest.raises(ValueError):
        SearxngSearch(get=get).search("   ")
    assert calls == []


def test_broken_or_hostless_urls_are_skipped_not_fatal():
    get, _ = fake_get(
        {
            "results": [
                {"title": "Roto", "url": "http://[::1", "content": "x"},
                {"title": "Sin host", "url": "http:///nohost", "content": "x"},
                {"title": "Bien", "url": "https://ok.com/a", "content": "ok"},
            ]
        }
    )

    assert [r.title for r in SearxngSearch(get=get).search("x")] == ["Bien"]


@pytest.mark.parametrize(
    "answer",
    [
        {"results": 5},
        {"no_results": []},
    ],
)
def test_results_that_are_not_a_list_are_unavailable(answer):
    get, _ = fake_get(answer)

    with pytest.raises(WebSearchUnavailable):
        SearxngSearch(get=get).search("clima")


def test_truncated_answer_is_unavailable():
    get, _ = fake_get(http.client.IncompleteRead(b"{"))

    with pytest.raises(WebSearchUnavailable):
        SearxngSearch(get=get).search("clima")
