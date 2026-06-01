"""Unit/example tests for ``ai_shared.search.TavilySearch`` (Task 5.1).

These pin concrete behaviors of the Tavily wrapper against an injected stub
client — no live ``tavily`` client, no network, and no real API key. They cover:

- normalized ranked results (title/url/content/rank in provider order),
- capping at the configured max preserving ranked order (Requirement 6.1),
- zero results and results-fewer-than-max,
- ``SearchError`` on a provider failure/timeout, surfacing the provider reason,
- ``SearchError`` carrying ``sub_question`` when supplied (Requirement 7.9),
- unicode content round-trips through normalization,
- the per-call ``max_results`` / ``timeout`` are forwarded to the provider.
"""

from __future__ import annotations

import pytest

from ai_shared.errors import SearchError
from ai_shared.search import DEFAULT_MAX_RESULTS, TavilySearch, WebResult


class _FakeSettings:
    tavily_api_key = "test-key"


def _hit(title: str, url: str, content: str) -> dict:
    return {"title": title, "url": url, "content": content}


class _StubClient:
    """Records the last ``search`` kwargs and returns a canned Tavily-shaped dict."""

    def __init__(self, results):
        self._results = results
        self.last_kwargs: dict | None = None

    def search(self, **kwargs):
        self.last_kwargs = kwargs
        return {"results": list(self._results)}


class _RaisingClient:
    def __init__(self, exc: BaseException):
        self._exc = exc

    def search(self, **kwargs):
        raise self._exc


def _results(n: int) -> list[dict]:
    return [_hit(f"T{i}", f"https://example.com/{i}", f"body {i}") for i in range(n)]


def test_returns_normalized_ranked_results() -> None:
    """Each hit maps to a WebResult with fields and a 1-based rank in order."""
    client = _StubClient(_results(3))
    search = TavilySearch(_FakeSettings(), client=client)

    out = search.search("what is rag?")

    assert [type(r) for r in out] == [WebResult, WebResult, WebResult]
    assert [r.rank for r in out] == [1, 2, 3]
    assert [r.url for r in out] == [
        "https://example.com/0",
        "https://example.com/1",
        "https://example.com/2",
    ]
    assert out[0].title == "T0"
    assert out[0].content == "body 0"


def test_caps_at_configured_max_preserving_order() -> None:
    """More results than the cap -> only the first `max` kept, ranks 1..max."""
    client = _StubClient(_results(25))
    search = TavilySearch(_FakeSettings(), client=client, max_results=10)

    out = search.search("q")

    assert len(out) == 10
    assert [r.rank for r in out] == list(range(1, 11))
    # Order preserved: first 10 source urls, in order.
    assert [r.url for r in out] == [f"https://example.com/{i}" for i in range(10)]
    # The cap is forwarded to the provider too.
    assert client.last_kwargs["max_results"] == 10


def test_default_max_results_is_ten() -> None:
    """The default cap matches Requirement 6.1 (up to 10)."""
    client = _StubClient(_results(50))
    search = TavilySearch(_FakeSettings(), client=client)
    out = search.search("q")
    assert DEFAULT_MAX_RESULTS == 10
    assert len(out) == 10


def test_per_call_max_results_override() -> None:
    """A per-call max_results overrides the instance default."""
    client = _StubClient(_results(8))
    search = TavilySearch(_FakeSettings(), client=client, max_results=10)
    out = search.search("q", max_results=3)
    assert len(out) == 3
    assert [r.rank for r in out] == [1, 2, 3]


def test_fewer_results_than_max_returns_all() -> None:
    """Results fewer than the cap are all returned, ranked in order."""
    client = _StubClient(_results(2))
    search = TavilySearch(_FakeSettings(), client=client, max_results=10)
    out = search.search("q")
    assert len(out) == 2
    assert [r.rank for r in out] == [1, 2]


def test_zero_results_returns_empty_list() -> None:
    """Zero provider results -> empty list (no error)."""
    client = _StubClient([])
    search = TavilySearch(_FakeSettings(), client=client)
    assert search.search("q") == []


def test_unicode_content_preserved() -> None:
    """Unicode in titles/content round-trips through normalization."""
    client = _StubClient([_hit("café ☕ 漢字", "https://example.com/u", "naïve – 你好")])
    search = TavilySearch(_FakeSettings(), client=client)
    out = search.search("q")
    assert out[0].title == "café ☕ 漢字"
    assert out[0].content == "naïve – 你好"


def test_missing_fields_default_to_empty_strings() -> None:
    """A hit missing fields still yields a WebResult with empty-string defaults."""
    client = _StubClient([{"url": "https://example.com/x"}])
    search = TavilySearch(_FakeSettings(), client=client)
    out = search.search("q")
    assert out[0].url == "https://example.com/x"
    assert out[0].title == ""
    assert out[0].content == ""
    assert out[0].rank == 1


def test_timeout_is_forwarded_to_provider() -> None:
    """The per-call timeout is passed through to the provider."""
    client = _StubClient(_results(1))
    search = TavilySearch(_FakeSettings(), client=client)
    search.search("q", timeout=12.5)
    assert client.last_kwargs["timeout"] == 12.5


def test_provider_failure_raises_search_error_with_reason() -> None:
    """A provider exception is mapped to SearchError surfacing the reason."""
    search = TavilySearch(_FakeSettings(), client=_RaisingClient(RuntimeError("boom")))
    with pytest.raises(SearchError) as ei:
        search.search("q")
    assert "boom" in ei.value.reason
    assert ei.value.sub_question is None


def test_provider_timeout_raises_search_error() -> None:
    """A timeout is mapped to SearchError (the provider reason is preserved)."""
    search = TavilySearch(_FakeSettings(), client=_RaisingClient(TimeoutError("timed out")))
    with pytest.raises(SearchError) as ei:
        search.search("q", timeout=30.0)
    assert "timed out" in ei.value.reason


def test_failure_attaches_sub_question() -> None:
    """When sub_question is supplied, it rides on the raised SearchError (Req 7.9)."""
    search = TavilySearch(_FakeSettings(), client=_RaisingClient(RuntimeError("nope")))
    with pytest.raises(SearchError) as ei:
        search.search("q", sub_question="What are the risks?")
    assert ei.value.sub_question == "What are the risks?"
    assert ei.value.details.get("sub_question") == "What are the risks?"


def test_preexisting_search_error_is_not_rewrapped() -> None:
    """If the client itself raises a SearchError, it propagates unchanged."""
    original = SearchError(reason="already structured", sub_question="sq")
    search = TavilySearch(_FakeSettings(), client=_RaisingClient(original))
    with pytest.raises(SearchError) as ei:
        search.search("q")
    assert ei.value is original


def test_webresult_to_json() -> None:
    """WebResult.to_json carries the normalized fields for SSE/persistence."""
    r = WebResult(title="t", url="u", content="c", rank=2)
    assert r.to_json() == {"title": "t", "url": "u", "content": "c", "rank": 2}
