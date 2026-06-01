"""JSON serialization for the Web Agent history responses (Requirements 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` and
:class:`ai_shared.history.WebAgentRecord` into JSON-able dicts for the
``GET /history`` (newest-first summaries) and ``GET /history/{id}`` (full record)
endpoints. Timestamps are emitted as ISO-8601 strings.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import HistorySummary, ProjectId, WebAgentRecord

__all__ = ["summary_to_json", "record_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a list-view summary (id, timestamp, short label)."""
    return {
        "id": str(summary.id),
        "project_id": ProjectId.WEB_AGENT.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def record_to_json(record_id: str, record: WebAgentRecord) -> dict[str, Any]:
    """Serialize a full web-agent record for the history detail view.

    Mirrors the persisted columns (Requirement 12.7): the question (input), and the
    synthesized answer plus the citations as source URLs (outputs), with the
    creation timestamp.
    """
    return {
        "id": record_id,
        "project_id": ProjectId.WEB_AGENT.value,
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "question": record.question,
        },
        "outputs": {
            "answer": record.answer,
            "citations": record.citations,
        },
    }
