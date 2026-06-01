"""Shared fakes/fixtures for the Capstone test suite.

These doubles let the validate -> plan -> (tool/retrieval) -> synthesize -> persist
flow and the document-ingestion flow be tested without a live LLM_Gateway, a live HF
embeddings client, a real Chroma store, a real MCP transport, or a real Database:

- :class:`FakeCompleteClient` — stands in for :class:`ai_shared.llm_client.LLMClient`
  by exposing an ``async def complete(...)`` that returns scripted
  :class:`ai_shared.llm_types.Completion` objects and can raise a gateway
  error/timeout on a chosen call.
- :class:`FakeEmbeddings` — stands in for :class:`ai_shared.embeddings.HFEmbeddings`
  by exposing ``embed`` / ``embed_one`` that return deterministic vectors and can
  raise :class:`ai_shared.errors.EmbeddingsError` on a chosen call.
- :class:`FakeVectorStore` — stands in for
  :class:`ai_shared.vectorstore.ChromaVectorStore` by exposing ``add`` / ``query``
  that record state and can raise :class:`ai_shared.errors.EmbeddingsError`.
- :class:`StubRepository` — a :class:`ai_shared.history.HistoryRepository`
  look-alike whose ``save_record`` records calls and returns a kind-discriminated
  capstone id (or raises :class:`ai_shared.errors.PersistenceError` on demand).
- :func:`make_query_hits` — build :class:`ai_shared.vectorstore.QueryHit` objects
  with ``doc_name`` metadata for the RAG retriever.
"""

from __future__ import annotations

from typing import Sequence

from ai_shared.errors import EmbeddingsError, PersistenceError
from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneTaskRecord,
    ProjectId,
)
from ai_shared.llm_types import Completion, Usage
from ai_shared.vectorstore import QueryHit


class FakeCompleteClient:
    """Fake LLMClient: returns scripted ``complete`` results in call order."""

    def __init__(
        self,
        contents: Sequence[str] = ("synthesized answer",),
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
        content = self._contents[index] if index < len(self._contents) else self._contents[-1]
        return Completion(content=content, usage=Usage(prompt_tokens=1, output_tokens=1, total_tokens=2))


class FakeEmbeddings:
    """Fake HFEmbeddings: deterministic vectors; can raise on a chosen call."""

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
    """Fake ChromaVectorStore: records adds, returns scripted query hits."""

    def __init__(
        self,
        *,
        hits: list[QueryHit] | None = None,
        raise_on_add: bool = False,
        raise_on_query: bool = False,
        fail_reason: str = "vector store unavailable",
    ) -> None:
        self._hits = hits
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
        if self._hits is not None:
            return list(self._hits[:top_k])
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
    """A HistoryRepository look-alike for unit tests (no real Database).

    ``save_record`` returns a ``kind``-discriminated capstone id (``"task:<n>"`` /
    ``"ingest:<n>"``, mirroring the real repository's BUG-003 behavior) so a service
    relying on the discriminated id shape works against the stub too.
    """

    def __init__(self, *, should_fail: bool = False, saved_id: int = 1) -> None:
        self.should_fail = should_fail
        self.saved_id = saved_id
        self.saved: list[tuple[ProjectId, object]] = []

    def save_record(self, project: ProjectId, record: object):
        self.saved.append((project, record))
        if self.should_fail:
            raise PersistenceError(reason="injected failure")
        if isinstance(record, CapstoneTaskRecord):
            return f"task:{self.saved_id}"
        if isinstance(record, CapstoneIngestRecord):
            return f"ingest:{self.saved_id}"
        return self.saved_id


def make_query_hits(sources: Sequence[str]) -> list[QueryHit]:
    """Build :class:`QueryHit` objects whose ``doc_name`` metadata names a source."""
    return [
        QueryHit(
            id=f"chunk-{i}",
            document_text=f"chunk text {i}",
            metadata={"doc_name": source},
            distance=0.0,
        )
        for i, source in enumerate(sources)
    ]
