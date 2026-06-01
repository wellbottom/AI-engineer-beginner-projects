"""Shared fakes/fixtures for the LLM Playground test suite.

These doubles let the streaming + persistence logic be tested without a live
LLM_Gateway or a real Database:

- :class:`FakeStreamClient` — stands in for :class:`ai_shared.llm_client.LLMClient`
  by exposing an ``async def stream(...)`` that records the kwargs it was called
  with (so parameter pass-through is checkable) and yields scripted
  :class:`ai_shared.llm_types.StreamEvent` objects, optionally raising a gateway
  error mid-stream.
- :class:`RecordingSDKClient` — a fake *openai-style* async client (exposes
  ``chat.completions.create``) used to drive the **real** ``LLMClient`` so the
  request params it builds for the gateway can be asserted (Property 4).
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


# --------------------------------------------------------------------------- #
# Fake openai-style SDK client to drive the REAL LLMClient (Property 4).
# --------------------------------------------------------------------------- #
class _Delta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.delta = _Delta(content)


class _UsageObj:
    def __init__(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


class _Chunk:
    def __init__(self, content: str | None, usage: _UsageObj | None = None) -> None:
        self.choices = [_Choice(content)]
        self.usage = usage


class _FakeAsyncStream:
    """Async iterator over scripted chunks (mimics an openai streaming response)."""

    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = list(chunks)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> _Chunk:
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._i]
        self._i += 1
        return chunk


class _RecordingCompletions:
    def __init__(self, store: list[dict]) -> None:
        self._store = store

    async def create(self, **params):
        self._store.append(params)
        # A single content chunk followed by a usage-bearing trailer so the real
        # LLMClient.stream completes normally with a terminal `done`.
        return _FakeAsyncStream(
            [
                _Chunk("hello"),
                _Chunk(None, usage=_UsageObj(3, 5, 8)),
            ]
        )


class RecordingSDKClient:
    """Fake openai async client capturing the params passed to ``create``."""

    def __init__(self) -> None:
        self.params: list[dict] = []
        self.chat = type(
            "_Chat", (), {"completions": _RecordingCompletions(self.params)}
        )()


# --------------------------------------------------------------------------- #
# Stub HistoryRepository.
# --------------------------------------------------------------------------- #
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
