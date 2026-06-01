"""JSON serialization for history responses (Requirements 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` and
:class:`ai_shared.history.PlaygroundRecord` into JSON-able dicts for the
``GET /history`` (newest-first summaries) and ``GET /history/{id}`` (full record)
endpoints. Timestamps are emitted as ISO-8601 strings.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import HistorySummary, PlaygroundRecord, ProjectId

__all__ = ["summary_to_json", "record_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a list-view summary (id, timestamp, short label)."""
    return {
        "id": str(summary.id),
        "project_id": ProjectId.PLAYGROUND.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def record_to_json(record_id: str, record: PlaygroundRecord) -> dict[str, Any]:
    """Serialize a full playground record for the history detail view.

    Mirrors the persisted columns (Requirement 12.5): prompt, system prompt,
    temperature, max output tokens, model, full response text, token usage, and
    the creation timestamp.
    """
    return {
        "id": record_id,
        "project_id": ProjectId.PLAYGROUND.value,
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "prompt": record.prompt,
            "system_prompt": record.system_prompt,
            "temperature": record.temperature,
            "max_tokens": record.max_tokens,
            "model": record.model,
        },
        "outputs": {
            "response_text": record.response_text,
            "usage": record.usage,
        },
    }
