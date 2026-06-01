"""JSON serialization for the Support Chatbot history responses (Req. 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` (list
view) and this service's :class:`app.history_read.SessionDetail` (detail view) into
JSON-able dicts for ``GET /history`` (newest-first session summaries) and
``GET /history/{id}`` (a session's full ordered turns). Timestamps are emitted as
ISO-8601 strings.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import HistorySummary, ProjectId

from .history_read import SessionDetail

__all__ = ["summary_to_json", "session_detail_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a session list-view summary (id, timestamp, short label).

    For the chatbot the summary ``id`` is the session row's surrogate id and the
    ``label`` is the conversation's ``session_id`` (set by the shared repository).
    """
    return {
        "id": str(summary.id),
        "project_id": ProjectId.SUPPORT.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def session_detail_to_json(detail: SessionDetail) -> dict[str, Any]:
    """Serialize a session's full ordered turn list for the detail view.

    Mirrors the persisted relational shape (Requirement 12.6): the session id plus
    every turn's user message, assistant reply, and timestamp, in order.
    """
    return {
        "id": str(detail.session_pk),
        "project_id": ProjectId.SUPPORT.value,
        "created_at": detail.created_at.isoformat(),
        "inputs": {"session_id": detail.session_id},
        "outputs": {
            "session_id": detail.session_id,
            "turns": [
                {
                    "user_message": t.user_message,
                    "assistant_reply": t.assistant_reply,
                    "created_at": t.created_at.isoformat(),
                }
                for t in detail.turns
            ],
        },
    }
