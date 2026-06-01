"""Unit/example tests for ``ai_shared.vectorstore.ChromaVectorStore`` (Task 5.1).

Two layers:

1. **Real local Chroma round-trip** — when ``chromadb`` is importable, an
   add-then-query round-trip runs against a real ``PersistentClient`` rooted in a
   pytest ``tmp_path`` (no network, no API key). Skipped if ``chromadb`` is not
   installed so the suite stays green in a stripped-down environment.
2. **Injected-stub logic tests** — capping/normalization/error-mapping are pinned
   against a lightweight stub client, so the wrapper's logic is testable without
   ``chromadb`` at all.

Covers: add-then-query round-trip, top-k cap, query on an empty collection,
metadata with/without ``sub_question_id``, ``doc_name`` vs ``source_url`` metadata,
empty-add no-op, ``top_k<=0``, and ``EmbeddingsError`` on add/query failures.
"""

from __future__ import annotations

import pytest

from ai_shared.errors import EmbeddingsError
from ai_shared.vectorstore import ChromaVectorStore, QueryHit, VectorRecord

try:  # pragma: no cover - import guard
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # pragma: no cover
    _HAS_CHROMADB = False


class _FakeSettings:
    def __init__(self, chroma_path: str = "./.chroma") -> None:
        self.chroma_path = chroma_path


# --------------------------------------------------------------------------- #
# 1. Real local Chroma round-trip (tmp dir) — skipped if chromadb is absent.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb not installed")
def test_real_chroma_add_then_query_roundtrip(tmp_path) -> None:
    """add() then query() against a real local persistent Chroma returns the doc."""
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    store = ChromaVectorStore(_FakeSettings(str(tmp_path / "chroma")), client=client)

    added = store.add(
        "research",
        [
            VectorRecord(
                id="d1",
                embedding=[1.0, 0.0, 0.0],
                document_text="alpha doc",
                metadata={"source_url": "https://example.com/a", "sub_question_id": 1},
            ),
            VectorRecord(
                id="d2",
                embedding=[0.0, 1.0, 0.0],
                document_text="beta doc",
                metadata={"source_url": "https://example.com/b"},
            ),
        ],
    )
    assert added == 2

    hits = store.query("research", [1.0, 0.0, 0.0], top_k=1)
    assert len(hits) == 1
    assert isinstance(hits[0], QueryHit)
    assert hits[0].id == "d1"
    assert hits[0].document_text == "alpha doc"
    assert hits[0].metadata.get("source_url") == "https://example.com/a"
    assert hits[0].metadata.get("sub_question_id") == 1


@pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb not installed")
def test_real_chroma_query_on_empty_collection_returns_empty(tmp_path) -> None:
    """Querying a freshly-created (empty) collection yields no hits, no error."""
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    store = ChromaVectorStore(_FakeSettings(str(tmp_path / "chroma")), client=client)
    assert store.query("empty", [0.1, 0.2, 0.3], top_k=5) == []


@pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb not installed")
def test_real_chroma_topk_caps_results(tmp_path) -> None:
    """top_k caps the number of returned hits."""
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    store = ChromaVectorStore(_FakeSettings(str(tmp_path / "chroma")), client=client)
    store.add(
        "cap",
        [
            VectorRecord(id=f"d{i}", embedding=[float(i), 0.0], document_text=f"doc {i}", metadata={"doc_name": f"f{i}"})
            for i in range(5)
        ],
    )
    hits = store.query("cap", [0.0, 0.0], top_k=2)
    assert len(hits) == 2


# --------------------------------------------------------------------------- #
# 2. Injected-stub logic tests — run without chromadb installed.
# --------------------------------------------------------------------------- #


class _StubCollection:
    def __init__(self, query_result=None, add_exc=None, query_exc=None):
        self._query_result = query_result
        self._add_exc = add_exc
        self._query_exc = query_exc
        self.added: dict | None = None
        self.queried: dict | None = None

    def add(self, **kwargs):
        if self._add_exc is not None:
            raise self._add_exc
        self.added = kwargs

    def query(self, **kwargs):
        if self._query_exc is not None:
            raise self._query_exc
        self.queried = kwargs
        return self._query_result


class _StubClient:
    def __init__(self, collection=None, collection_exc=None):
        self._collection = collection or _StubCollection()
        self._collection_exc = collection_exc
        self.requested_names: list[str] = []

    def get_or_create_collection(self, name):
        self.requested_names.append(name)
        if self._collection_exc is not None:
            raise self._collection_exc
        return self._collection


def test_add_forwards_records_in_chroma_shape() -> None:
    """add() forwards ids/embeddings/documents/metadatas in the design's shape."""
    coll = _StubCollection()
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(coll))
    n = store.add(
        "c",
        [
            VectorRecord(id="x", embedding=[0.1, 0.2], document_text="text", metadata={"doc_name": "f.txt"}),
        ],
    )
    assert n == 1
    assert coll.added["ids"] == ["x"]
    assert coll.added["embeddings"] == [[0.1, 0.2]]
    assert coll.added["documents"] == ["text"]
    assert coll.added["metadatas"] == [{"doc_name": "f.txt"}]


def test_add_empty_is_noop() -> None:
    """Adding zero records does not touch the collection and returns 0."""
    client = _StubClient()
    store = ChromaVectorStore(_FakeSettings(), client=client)
    assert store.add("c", []) == 0
    assert client.requested_names == []


def test_query_normalizes_chroma_nested_response() -> None:
    """query() maps Chroma's per-query nested lists onto ordered QueryHit objects."""
    result = {
        "ids": [["a", "b"]],
        "documents": [["doc a", "doc b"]],
        "metadatas": [[{"source_url": "u-a", "sub_question_id": 2}, {"doc_name": "f"}]],
        "distances": [[0.1, 0.42]],
    }
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(_StubCollection(query_result=result)))
    hits = store.query("c", [0.0, 0.0], top_k=5)
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].document_text == "doc a"
    assert hits[0].metadata == {"source_url": "u-a", "sub_question_id": 2}
    assert hits[0].distance == 0.1
    assert hits[1].metadata == {"doc_name": "f"}


def test_query_top_k_forwarded_and_zero_returns_empty() -> None:
    """n_results is forwarded; top_k<=0 short-circuits to [] without querying."""
    coll = _StubCollection(query_result={"ids": [["a"]], "documents": [["d"]], "metadatas": [[{}]], "distances": [[0.0]]})
    client = _StubClient(coll)
    store = ChromaVectorStore(_FakeSettings(), client=client)

    store.query("c", [0.0], top_k=3)
    assert coll.queried["n_results"] == 3

    coll.queried = None
    assert store.query("c", [0.0], top_k=0) == []
    assert coll.queried is None


def test_query_empty_response_returns_empty_list() -> None:
    """An empty Chroma response yields no hits."""
    result = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(_StubCollection(query_result=result)))
    assert store.query("c", [0.0], top_k=5) == []


def test_add_failure_raises_embeddings_error() -> None:
    """An add failure is surfaced as EmbeddingsError with a clear action."""
    coll = _StubCollection(add_exc=RuntimeError("disk full"))
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(coll))
    with pytest.raises(EmbeddingsError) as ei:
        store.add("c", [VectorRecord(id="x", embedding=[0.0], document_text="t", metadata={})])
    assert ei.value.action == "vector store add"
    assert "disk full" in ei.value.reason


def test_query_failure_raises_embeddings_error() -> None:
    """A query failure is surfaced as EmbeddingsError with a clear action."""
    coll = _StubCollection(query_exc=RuntimeError("index error"))
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(coll))
    with pytest.raises(EmbeddingsError) as ei:
        store.query("c", [0.0], top_k=5)
    assert ei.value.action == "vector store query"
    assert "index error" in ei.value.reason


def test_collection_failure_raises_embeddings_error() -> None:
    """A get/create collection failure is surfaced as EmbeddingsError."""
    store = ChromaVectorStore(_FakeSettings(), client=_StubClient(collection_exc=RuntimeError("no perms")))
    with pytest.raises(EmbeddingsError) as ei:
        store.get_or_create_collection("c")
    assert ei.value.action == "vector store collection"
    assert "no perms" in ei.value.reason


def test_queryhit_to_json() -> None:
    """QueryHit.to_json carries id/document_text/metadata/distance."""
    hit = QueryHit(id="i", document_text="d", metadata={"k": "v"}, distance=0.3)
    assert hit.to_json() == {"id": "i", "document_text": "d", "metadata": {"k": "v"}, "distance": 0.3}
