"""JSON serialization for the Capstone history responses (Requirements 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` and the
two capstone record variants (:class:`ai_shared.history.CapstoneTaskRecord` and
:class:`ai_shared.history.CapstoneIngestRecord`) into JSON-able dicts for the
``GET /history`` (newest-first merged summaries) and ``GET /history/{id}`` (full
record) endpoints. Timestamps are emitted as ISO-8601 strings.

**Discriminated string ids (BUG-003).** Capstone persists into two independently
sequenced tables, so its history ids are ``kind``-discriminated **strings** of the
form ``"task:<n>"`` / ``"ingest:<n>"``. ``GET /history`` returns those discriminated
ids in its summaries and ``GET /history/{id}`` accepts the discriminated **string**
id — never a bare int — so a task row and an ingest row sharing a numeric id never
shadow each other.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneTaskRecord,
    HistorySummary,
    ProjectId,
)

__all__ = ["summary_to_json", "record_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a list-view summary (discriminated id, timestamp, short label).

    ``summary.id`` is already the ``kind``-discriminated string id
    (``"task:<n>"`` / ``"ingest:<n>"``) produced by ``HistoryRepository`` for the
    capstone project, so it is emitted as-is (BUG-003).
    """
    return {
        "id": str(summary.id),
        "project_id": ProjectId.CAPSTONE.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def _task_to_json(record_id: str, record: CapstoneTaskRecord) -> dict[str, Any]:
    """Serialize a full capstone task-run record (Requirement 12.10).

    Mirrors the persisted columns: the task text (input), and the final answer, the
    list of MCP tools invoked (each with its ok/failure status), the referenced
    source documents, and the step-limit-reached indication (outputs), with the
    creation timestamp.
    """
    return {
        "id": record_id,
        "project_id": ProjectId.CAPSTONE.value,
        "kind": "task",
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "task": record.task_text,
        },
        "outputs": {
            "answer": record.final_answer,
            "tools_invoked": record.tools_invoked,
            "sources": record.sources,
            "step_limit_reached": record.step_limit_reached,
        },
    }


def _ingest_to_json(record_id: str, record: CapstoneIngestRecord) -> dict[str, Any]:
    """Serialize a full capstone ingestion record (Requirement 12.11).

    Mirrors the persisted columns: the names of the ingested documents (output) with
    the creation timestamp. The ingestion endpoint has no separate "input" beyond the
    uploaded files, so ``inputs`` carries the document names too for symmetry.
    """
    return {
        "id": record_id,
        "project_id": ProjectId.CAPSTONE.value,
        "kind": "ingest",
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "documents": record.documents,
        },
        "outputs": {
            "documents": record.documents,
        },
    }


def record_to_json(
    record_id: str, record: CapstoneTaskRecord | CapstoneIngestRecord
) -> dict[str, Any]:
    """Serialize a full capstone record (task run or ingestion) by its variant.

    Dispatches on the concrete record type so the discriminated id (``"task:<n>"`` /
    ``"ingest:<n>"``) renders the correct shape for the history detail view.
    """
    if isinstance(record, CapstoneTaskRecord):
        return _task_to_json(record_id, record)
    return _ingest_to_json(record_id, record)
