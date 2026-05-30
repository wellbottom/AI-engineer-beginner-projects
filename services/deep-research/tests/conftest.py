"""Shared fakes/fixtures for the Deep Research test suite.

These doubles let the decompose → research → synthesize → persist pipeline be
tested without a live Tavily client, a live HF embeddings client, a real Chroma
store, a live LLM_Gateway, or a real Database:

- :class:`FakeCompleteClient` — stands in for :class:`ai_shared.llm_client.LLMClient`
  by exposing an ``async def complete(...)`` that returns scripted
  :class:`ai_shared.llm_types.Completion` objects (one per call, in order) and can
  raise a gateway error/timeout on a chosen call.
- :class:`FakeSearch` — stands in for :class:`ai_shared.search.TavilySearch` by
  exposing a ``search(query, *, max_results=None, timeout=..., sub_question=...)``
  that records the kwargs it was called with and either returns scripted results
  (per query) or raises :class:`ai_shared.errors.SearchError` (failure/timeout),
  optionally only for a specific sub-question.
- :class:`FakeEmbeddings` — stands in for :class:`ai_shared.embeddings.HFEmbeddings`
  by exposing ``embed`` / ``embed_one`` that return deterministic vectors and can
  raise :class:`ai_shared.errors.EmbeddingsError` on a chosen call.
- :class:`FakeVectorStore` — stands in for
  :class:`ai_shared.vectorstore.ChromaVectorStore` by exposing ``add`` / ``query``
  that record state and can raise :class:`ai_shared.errors.EmbeddingsError`.
- :class:`StubRepository` — a :class:`ai_shared.history.HistoryRepository`
  look-alike whose ``save_record`` records calls and can succeed or raise
  :class:`ai_shared.errors.PersistenceError` on demand.
"""

from __future__ import annotations

from typing import Sequence

from ai_shared.errors import EmbeddingsError, PersistenceError, SearchError
from ai_shared.history import ProjectId
from ai_shared.llm_types import Completion, Usage
from ai_shared.search import WebResult
from ai_shared.vectorstore import QueryHit


class FakeCompleteClient:
    """Fake LLMClient: returns scripted ``complete`` results in call order.

    ``contents`` supplies the text for each successive ``complete`` call (the first
    is typically the decomposition, then one per report section). If a call index
    is in ``raise_on``, that call raises ``raise_exc`` instead.
    """

    def __init__(
        self,
        contents: Sequence[str],
        *,
        raise_on: set[int] | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._contents = list(contents)
        self._raise_on = raise_on or set()
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    async def complete(
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        timeout: float = 60.0,
    ) -> Completion:
        index = len(self.calls)
        self.calls.append({"messages": messages, "timeout": timeout})
        if index in self._raise_on and self._raise_exc is not None:
            raise self._raise_exc
        content = self._contents[index] if index < len(self._contents) else ""
        return Completion(content=content, usage=Usage(prompt_tokens=1, output_tokens=1, total_tokens=2))


class FakeSearch:
    """Fake TavilySearch: returns scripted results per query and records kwargs.

    ``results_by_query`` maps a sub-question text to its results; ``default_results``
    is used for any unmapped query. If ``fail_on`` matches a query's
    ``sub_question`` (or is the sentinel ``"*"``), a ``SearchError`` is raised.
    """

    def __init__(
        self,
        *,
        results_by_query: dict[str, list[WebResult]] | None = None,
        default_results: list[WebResult] | None = None,
        fail_on: str | None = None,
        fail_reason: str = "provider unavailable",
    ) -> None:
        self._results_by_query = results_by_query or {}
        self._default_results = default_results
        self._fail_on = fail_on
        self._fail_reason = fail_reason
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
        if self._fail_on is not None and self._fail_on in ("*", query, sub_question):
            raise SearchError(reason=self._fail_reason, sub_question=sub_question)
        if query in self._results_by_query:
            return list(self._results_by_query[query])
        if self._default_results is not None:
            return list(self._default_results)
        return make_results(2)


class FakeEmbeddings:
    """Fake HFEmbeddings: deterministic vectors; can raise on a chosen call.

    Each successful call increments ``call_index``; if it is in ``raise_on``, an
    ``EmbeddingsError`` is raised. ``embed`` returns one vector per input text.
    """

    def __init__(
        self,
        *,
        dim: int = 3,
        raise_on: set[int] | None = None,
        fail_reason: str = "embeddings provider unavailable",
    ) -> None:
        self._dim = dim
        self._raise_on = raise_on or set()
        self._fail_reason = fail_reason
        self.call_index = 0
        self.embed_calls: list[list[str]] = []
        self.embed_one_calls: list[str] = []

    def _maybe_fail(self) -> None:
        index = self.call_index
        self.call_index += 1
        if index in self._raise_on:
            raise EmbeddingsError(reason=self._fail_reason)

    def embed(self, texts, *, timeout: float = 30.0) -> list[list[float]]:
        items = list(texts)
        self.embed_calls.append(items)
        self._maybe_fail()
        return [[float(i + 1)] * self._dim for i in range(len(items))]

    def embed_one(self, text: str, *, timeout: float = 30.0) -> list[float]:
        self.embed_one_calls.append(text)
        self._maybe_fail()
        return [1.0] * self._dim


class FakeVectorStore:
    """Fake ChromaVectorStore: records adds, returns scripted query hits.

    ``add`` stores the records keyed by collection; ``query`` returns
    :class:`QueryHit` objects derived from the stored documents (or scripted hits).
    Either can be made to raise an ``EmbeddingsError``.
    """

    def __init__(
        self,
        *,
        raise_on_add: bool = False,
        raise_on_query: bool = False,
        fail_reason: str = "vector store unavailable",
    ) -> None:
        self._raise_on_add = raise_on_add
        self._raise_on_query = raise_on_query
        self._fail_reason = fail_reason
        self.added: dict[str, list] = {}
        self.add_calls = 0
        self.query_calls = 0

    def add(self, collection_name: str, records) -> int:
        self.add_calls += 1
        if self._raise_on_add:
            raise EmbeddingsError(action="vector store add", reason=self._fail_reason)
        items = list(records)
        self.added.setdefault(collection_name, []).extend(items)
        return len(items)

    def query(self, collection_name: str, embedding, *, top_k: int = 5) -> list[QueryHit]:
        self.query_calls += 1
        if self._raise_on_query:
            raise EmbeddingsError(action="vector store query", reason=self._fail_reason)
        stored = self.added.get(collection_name, [])
        hits: list[QueryHit] = []
        for record in stored[:top_k]:
            hits.append(
                QueryHit(
                    id=getattr(record, "id", ""),
                    document_text=getattr(record, "document_text", ""),
                    metadata=getattr(record, "metadata", {}),
                    distance=0.0,
                )
            )
        return hits


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


def make_results(n: int, *, start: int = 1, prefix: str = "sq") -> list[WebResult]:
    """Build ``n`` ranked :class:`WebResult` objects with distinct URLs."""
    return [
        WebResult(
            title=f"{prefix} Result {i}",
            url=f"https://example.com/{prefix}/{i}",
            content=f"content for {prefix} result {i}",
            rank=i,
        )
        for i in range(start, start + n)
    ]


def numbered_decomposition(n: int) -> str:
    """A decomposition output with ``n`` numbered, distinct sub-questions."""
    return "\n".join(f"{i}. Sub-question number {i}?" for i in range(1, n + 1))
