"""Shared fakes/fixtures for the Web Agent test suite.

These doubles let the search + synthesis + persistence logic be tested without a
live Tavily client, a live LLM_Gateway, or a real Database:

- :class:`FakeSearch` — stands in for :class:`ai_shared.search.TavilySearch` by
  exposing a ``search(query, *, max_results=None, timeout=...) -> list[WebResult]``
  method that records the kwargs it was called with and either returns scripted
  results or raises :class:`ai_shared.errors.SearchError` (failure/timeout).
- :class:`FakeStreamClient` — stands in for :class:`ai_shared.llm_client.LLMClient`
  by exposing an ``async def stream(...)`` that records the kwargs it was called
  with and yields scripted :class:`ai_shared.llm_types.StreamEvent` objects,
  optionally raising a gateway error/timeout mid-stream.
- :class:`StubRepository` — a :class:`ai_shared.history.HistoryRepository`
  look-alike whose ``save_record`` records calls and can succeed or raise
  :class:`ai_shared.errors.PersistenceError` on demand.
"""

from __future__ import annotations

from typing import AsyncIterator

from ai_shared.errors import PersistenceError, SearchError
from ai_shared.history import ProjectId
from ai_shared.llm_types import StreamEvent
from ai_shared.search import WebResult


class FakeSearch:
    """Fake TavilySearch: records ``search`` kwargs and returns/raises on demand."""

    def __init__(
        self,
        results: list[WebResult] | None = None,
        *,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._results = results or []
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        *,
        max_results=None,
        timeout: float = 30.0,
        sub_question=None,
    ) -> list[WebResult]:
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "timeout": timeout,
                "sub_question": sub_question,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return list(self._results)


class FakeStreamClient:
    """Fake LLMClient: records ``stream`` kwargs and yields scripted events."""

    def __init__(
        self,
        events: list[StreamEvent],
        *,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._events = events
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    async def stream(  # noqa: D401 - mirrors LLMClient.stream signature
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        timeout: float = 60.0,
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        for event in self._events:
            yield event
        if self._raise_exc is not None:
            raise self._raise_exc


class StubRepository:
    """A HistoryRepository look-alike for unit tests (no real Database)."""

    def __init__(self, *, should_fail: bool = False, saved_id: int = 1) -> None:
        self.should_fail = should_fail
        self.saved_id = saved_id
        self.saved: list[tuple[ProjectId, object]] = []

    def save_record(self, project: ProjectId, record: object):
        self.saved.append((project, record))
        if self.should_fail:
            raise PersistenceError(reason="injected failure")
        return self.saved_id


def make_results(n: int, *, start: int = 1) -> list[WebResult]:
    """Build ``n`` ranked :class:`WebResult` objects with distinct URLs.

    Ranks are 1-based and contiguous starting at ``start``; URLs/titles are derived
    from the rank so order and membership are easy to assert.
    """
    return [
        WebResult(
            title=f"Result {i}",
            url=f"https://example.com/{i}",
            content=f"content for result {i}",
            rank=i,
        )
        for i in range(start, start + n)
    ]


# A reusable SearchError for failure-path tests (provider failure or 30s timeout).
def search_failure(reason: str = "provider unavailable") -> SearchError:
    return SearchError(reason=reason)
