"""JSON serialization for the Deep Research history responses (Requirements 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` and
:class:`ai_shared.history.DeepResearchRecord` into JSON-able dicts for the
``GET /history`` (newest-first summaries) and ``GET /history/{id}`` (full record)
endpoints. Timestamps are emitted as ISO-8601 strings.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import DeepResearchRecord, HistorySummary, ProjectId

__all__ = ["summary_to_json", "record_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a list-view summary (id, timestamp, short label)."""
    return {
        "id": str(summary.id),
        "project_id": ProjectId.DEEP_RESEARCH.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def record_to_json(record_id: str, record: DeepResearchRecord) -> dict[str, Any]:
    """Serialize a full deep-research record for the history detail view.

    Mirrors the persisted columns (Requirement 12.8): the topic (input), and the
    generated sub-questions, the full report (title, introduction, one section per
    sub-question, conclusion), and the citations (outputs), with the creation
    timestamp.
    """
    return {
        "id": record_id,
        "project_id": ProjectId.DEEP_RESEARCH.value,
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "topic": record.topic,
        },
        "outputs": {
            "sub_questions": record.sub_questions,
            "report": record.report,
            "citations": record.citations,
        },
    }
