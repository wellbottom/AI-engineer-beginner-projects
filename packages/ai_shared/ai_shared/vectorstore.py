"""Chroma local persistent vector-store wrapper (Requirements 7.3, 9.3).

:class:`ChromaVectorStore` is a thin, framework-agnostic wrapper over a **local
persistent** Chroma client rooted at :attr:`Settings.chroma_path`. It is used by
Deep Research (store per-sub-question source content) and the Capstone RAG
pipeline (ingest documents, retrieve top-k chunks).

Capabilities:

- :meth:`get_or_create_collection` — get/create a named collection.
- :meth:`add` — add documents in the design's Chroma record shape
  ``{ id, embedding, document_text, metadata: { source_url | doc_name,
  sub_question_id? } }``.
- :meth:`query` — top-k retrieval by embedding (used by RAG and deep research).

**Error policy.** The shared error hierarchy has no dedicated vector-store error
type, and the design says not to invent one. Vector-store failures occur on the
embeddings/retrieval path (always paired with the Embeddings_Service in
Requirements 7.3 and 9.3), so this wrapper surfaces operational failures as
:class:`~ai_shared.errors.EmbeddingsError` with a clear ``action``
(``"vector store add"`` / ``"vector store query"`` / ``"vector store
collection"``) and the provider reason. This keeps deep-research and capstone
ingestion/retrieval failures inside the single "embeddings/ingestion failure"
bucket the requirements describe (7.7, 9.10), rather than introducing a new
class. (``PersistenceError`` is reserved for the PostgreSQL History_Store, so it
is intentionally not reused here.)

**Dependency isolation / testability.** ``chromadb`` is imported lazily (only
when a real client is first built), and a client can be injected via the
``client=`` constructor argument. This keeps the add/query/error-mapping logic
unit-testable with a stub — no ``chromadb`` install is required to exercise the
wrapper's logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

from .config import Settings
from .errors import EmbeddingsError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import chromadb

__all__ = ["VectorRecord", "QueryHit", "ChromaVectorStore", "DEFAULT_TOP_K"]

#: Default number of nearest neighbours returned by :meth:`ChromaVectorStore.query`.
DEFAULT_TOP_K: int = 5


@dataclass
class VectorRecord:
    """One document to store in Chroma (the design's Chroma record shape).

    ``metadata`` carries either a ``source_url`` (deep research) or a ``doc_name``
    (capstone ingestion), and optionally a ``sub_question_id``.
    """

    id: str
    embedding: list[float]
    document_text: str
    metadata: dict[str, Any]


@dataclass
class QueryHit:
    """One nearest-neighbour result from :meth:`ChromaVectorStore.query`."""

    id: str
    document_text: str
    metadata: dict[str, Any]
    distance: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_text": self.document_text,
            "metadata": dict(self.metadata),
            "distance": self.distance,
        }


class ChromaVectorStore:
    """Thin wrapper over a local persistent Chroma client.

    Args:
        settings: Loaded :class:`Settings` providing ``chroma_path`` (the local
            persistence root).
        client: Optional pre-built Chroma client exposing
            ``get_or_create_collection(name=...)`` (anything Chroma-compatible).
            When omitted, a real ``chromadb.PersistentClient(path=chroma_path)`` is
            created lazily on first use. Injecting a stub keeps the wrapper testable
            without ``chromadb`` installed.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: "chromadb.ClientAPI | Any | None" = None,
    ) -> None:
        self._settings = settings
        self._client = client

    @property
    def client(self) -> "chromadb.ClientAPI | Any":
        """The underlying Chroma client, built lazily from settings if needed."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> "chromadb.ClientAPI":
        """Construct a real local persistent Chroma client at ``chroma_path``."""
        import chromadb  # noqa: PLC0415 - intentional lazy import

        return chromadb.PersistentClient(path=self._settings.chroma_path)

    def get_or_create_collection(self, name: str) -> Any:
        """Get or create a named collection.

        Raises:
            EmbeddingsError: The vector store failed to get/create the collection.
        """
        try:
            return self.client.get_or_create_collection(name=name)
        except EmbeddingsError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY chroma/transport error
            raise EmbeddingsError(
                action="vector store collection",
                reason=str(exc) or None,
            ) from exc

    def add(self, collection_name: str, records: Sequence[VectorRecord]) -> int:
        """Add documents to a collection in the design's Chroma record shape.

        Args:
            collection_name: Target collection (created if absent).
            records: Documents to add. An empty sequence is a no-op returning 0.

        Returns:
            The number of records added.

        Raises:
            EmbeddingsError: The vector store add failed; carries the reason.
        """
        items = list(records)
        if not items:
            return 0

        collection = self.get_or_create_collection(collection_name)
        try:
            collection.add(
                ids=[r.id for r in items],
                embeddings=[list(r.embedding) for r in items],
                documents=[r.document_text for r in items],
                metadatas=[dict(r.metadata) for r in items],
            )
        except EmbeddingsError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY chroma/transport error
            raise EmbeddingsError(
                action="vector store add",
                reason=str(exc) or None,
            ) from exc
        return len(items)

    def query(
        self,
        collection_name: str,
        embedding: list[float],
        *,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[QueryHit]:
        """Return up to ``top_k`` nearest neighbours for ``embedding``.

        Args:
            collection_name: Collection to query (created if absent — an empty
                collection simply yields no hits).
            embedding: The query vector.
            top_k: Maximum neighbours to return (``<= 0`` returns ``[]``).

        Returns:
            A list of :class:`QueryHit` (possibly empty), nearest first.

        Raises:
            EmbeddingsError: The vector store query failed; carries the reason.
        """
        if top_k <= 0:
            return []

        collection = self.get_or_create_collection(collection_name)
        try:
            raw = collection.query(query_embeddings=[list(embedding)], n_results=top_k)
        except EmbeddingsError:
            raise
        except Exception as exc:  # noqa: BLE001 - map ANY chroma/transport error
            raise EmbeddingsError(
                action="vector store query",
                reason=str(exc) or None,
            ) from exc

        return _normalize_query(raw)


def _first_row(value: Any) -> list[Any]:
    """Extract row 0 from Chroma's per-query nested lists, tolerating shapes.

    Chroma returns ``{"ids": [[...]], "documents": [[...]], ...}`` where the outer
    list is per-query (we always send one query, so we take index 0). Returns ``[]``
    for missing/None entries.
    """
    if not value:
        return []
    first = value[0]
    return list(first) if first else []


def _normalize_query(raw: Any) -> list[QueryHit]:
    """Map a Chroma ``query`` response onto ordered :class:`QueryHit` objects."""
    if not isinstance(raw, dict):
        return []

    ids = _first_row(raw.get("ids"))
    documents = _first_row(raw.get("documents"))
    metadatas = _first_row(raw.get("metadatas"))
    distances = _first_row(raw.get("distances"))

    hits: list[QueryHit] = []
    for index, _id in enumerate(ids):
        hits.append(
            QueryHit(
                id=_id,
                document_text=documents[index] if index < len(documents) else "",
                metadata=dict(metadatas[index]) if index < len(metadatas) and metadatas[index] else {},
                distance=float(distances[index]) if index < len(distances) and distances[index] is not None else None,
            )
        )
    return hits
