"""Shared fakes/fixtures for the Support Chatbot test suite.

These doubles let the streaming + persistence logic be tested without a live
LLM_Gateway or a real Database:

- :class:`FakeStreamClient` — stands in for :class:`ai_shared.llm_client.LLMClient`
  by exposing an ``async def stream(...)`` that records the kwargs it was called
  with (so the assembled messages + 30s timeout are checkable) and yields scripted
  :class:`ai_shared.llm_types.StreamEvent` objects, optionally raising a gateway
  error/timeout mid-stream.
- :class:`StubRepository` — a :class:`ai_shared.history.HistoryRepository`
  look-alike whose ``save_record`` records calls and can succeed or raise
  :class:`ai_shared.errors.PersistenceError` on demand.
"""

from __future__ import annotations

from typing import AsyncIterator

from ai_shared.errors import PersistenceError
from ai_shared.history import ProjectId
from ai_shared.llm_types import StreamEvent


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
