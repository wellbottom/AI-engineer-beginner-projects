"""Document ingestion for the Capstone RAG store (Requirements 9.5, 9.10, 12.11).

Framework-agnostic pieces of ``POST /documents`` so they are unit/property-testable
without FastAPI, a live HF embeddings client, a real Chroma store, or a real
Database. The endpoint accepts uploads (≤ 10 MB each), embeds their text via the
Embeddings_Service, stores the embeddings in the Vector_Store (Chroma), and returns
a confirmation naming **exactly** the successfully ingested documents (Property 25).

Pure / framework-agnostic functions
------------------------------------
- :func:`validate_upload_size` — enforce the ≤ 10 MB per-document bound (Requirement
  9.5); an oversized document raises a :class:`ai_shared.errors.ValidationError`
  naming the offending document, so the provider is never contacted for it.
- :func:`chunk_text` — split a document's text into embeddable chunks (fixed-size
  character windows on whitespace boundaries).
- :func:`ingest_documents` — embed + store every submitted document and return the
  list of :class:`ai_shared.history.IngestedDoc` actually ingested (one entry per
  document, no extras/omissions — Property 25). An embeddings/vector-store failure
  raises :class:`ai_shared.errors.EmbeddingsError` identifying the ingestion failure
  (Requirement 9.10); nothing partial is confirmed.
- :func:`ingest_and_persist` — the route-level orchestration: ingest, build the
  confirmation body, persist a :class:`ai_shared.history.CapstoneIngestResult`
  best-effort (Requirement 12.11), and merge the persistence indication into the
  **non-streamed** JSON body (Requirement 12.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ai_shared.errors import ValidationError
from ai_shared.history import (
    CapstoneIngestResult,
    HistoryRepository,
    IngestedDoc,
    ProjectId,
    build_history_record,
)
from ai_shared.persistence import persist_record
from ai_shared.vectorstore import VectorRecord

__all__ = [
    "DocumentUpload",
    "validate_upload_size",
    "chunk_text",
    "ingest_documents",
    "ingest_and_persist",
    "MAX_DOC_BYTES",
    "CHUNK_SIZE",
    "ACTION",
]

#: Human-readable action label used on validation/error responses.
ACTION = "ingest documents"

#: Maximum size of a single uploaded document, in bytes (Requirement 9.5: 10 MB).
MAX_DOC_BYTES = 10 * 1024 * 1024

#: Approximate target chunk size (characters) for embedding document text.
CHUNK_SIZE = 1000


@dataclass
class DocumentUpload:
    """One submitted document: its file ``name`` and raw ``data`` bytes."""

    name: str
    data: bytes


def validate_upload_size(name: str, size: int) -> None:
    """Validate one document's size against the ≤ 10 MB bound (Requirement 9.5).

    Raises:
        ValidationError: When ``size`` exceeds :data:`MAX_DOC_BYTES`; names the
            offending document and the violated constraint so the caller can reject
            it without contacting the Embeddings_Service.
    """
    if size > MAX_DOC_BYTES:
        raise ValidationError(
            field="documents",
            constraint=f"each document must be at most {MAX_DOC_BYTES} bytes (10 MB)",
            action=ACTION,
            details={"document": name, "size": size},
        )


def _decode(data: bytes) -> str:
    """Decode document bytes to text (UTF-8, replacing undecodable bytes)."""
    if isinstance(data, str):  # tolerate already-decoded text in tests
        return data
    return data.decode("utf-8", errors="replace")


def chunk_text(text: str, *, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split ``text`` into chunks of at most ``chunk_size`` characters.

    Pure function. Splits on whitespace and greedily packs words into chunks so no
    chunk exceeds ``chunk_size`` (a single oversized word becomes its own chunk).
    Whitespace-only / empty text yields no chunks.
    """
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        added = len(word) + (1 if current else 0)
        if current and length + added > chunk_size:
            chunks.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += added
    if current:
        chunks.append(" ".join(current))
    return chunks


def ingest_documents(
    documents: list[DocumentUpload],
    *,
    embeddings: Any,
    vector_store: Any,
    collection: str,
) -> list[IngestedDoc]:
    """Embed + store every submitted document; return the ingested-document list.

    For each document: decode its text, chunk it, embed the chunks via the
    Embeddings_Service, and store the embeddings in the Vector_Store under
    ``collection`` (each record's ``metadata`` carries the ``doc_name``). Returns one
    :class:`IngestedDoc` per submitted document (with its chunk count) — exactly the
    set of successfully ingested documents, no extras or omissions (Property 25).

    A document whose text yields no chunks (empty/whitespace content) is still
    confirmed with ``chunks=0`` (it was accepted and processed without error). An
    embeddings/vector-store failure raises :class:`EmbeddingsError` identifying the
    ingestion failure (Requirement 9.10), and nothing is confirmed for the batch.

    Args:
        documents: The submitted, size-validated documents.
        embeddings: The Embeddings_Service wrapper (``embed(texts) -> vectors``).
        vector_store: The Vector_Store wrapper (``add(collection, records) -> int``).
        collection: The Chroma collection to store the embeddings in.

    Returns:
        The list of :class:`IngestedDoc` for the successfully ingested documents.

    Raises:
        EmbeddingsError: An embeddings or vector-store failure (Requirement 9.10).
    """
    ingested: list[IngestedDoc] = []
    for doc_index, doc in enumerate(documents):
        text = _decode(doc.data)
        chunks = chunk_text(text)
        if chunks:
            vectors = embeddings.embed(chunks)
            records = [
                VectorRecord(
                    id=f"{collection}-{doc_index}-{chunk_index}",
                    embedding=list(vector),
                    document_text=chunk,
                    metadata={"doc_name": doc.name, "chunk_index": chunk_index},
                )
                for chunk_index, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]
            vector_store.add(collection, records)
        ingested.append(IngestedDoc(name=doc.name, chunks=len(chunks)))
    return ingested


def ingest_and_persist(
    documents: list[DocumentUpload],
    *,
    embeddings: Any,
    vector_store: Any,
    repository: HistoryRepository,
    collection: str,
    operation_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Ingest documents, persist the ingestion record, and return the JSON body.

    The non-streamed counterpart to the task SSE driver: it ingests every document
    (Requirement 9.5), persists a :class:`CapstoneIngestResult` best-effort
    (Requirement 12.11), and returns a JSON body naming exactly the ingested
    documents plus the persistence indication merged into the body (Requirement
    12.4). An embeddings failure propagates as :class:`EmbeddingsError` (Requirement
    9.10) — nothing is persisted.

    Returns:
        The success JSON body: ``documents`` (the confirmation list of
        ``{name, chunks}``) and the ``persistence`` indication.
    """
    ingested = ingest_documents(
        documents, embeddings=embeddings, vector_store=vector_store, collection=collection
    )

    result = CapstoneIngestResult(documents=ingested)
    record = build_history_record(ProjectId.CAPSTONE, result)
    kwargs = (
        {} if operation_id_factory is None else {"operation_id_factory": operation_id_factory}
    )
    outcome = persist_record(repository, ProjectId.CAPSTONE, record, **kwargs)

    body: dict[str, Any] = {
        "documents": [{"name": doc.name, "chunks": doc.chunks} for doc in ingested],
    }
    return outcome.attach_to_body(body)
