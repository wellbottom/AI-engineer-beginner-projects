"""JSON serialization for the Image Service history responses (Requirements 13.1, 13.3).

Pure helpers that turn the shared :class:`ai_shared.history.HistorySummary` and
:class:`ai_shared.history.ImageRecord` into JSON-able dicts for the ``GET /history``
(newest-first summaries) and ``GET /history/{id}`` (full record) endpoints.
Timestamps are emitted as ISO-8601 strings.

The detail view **re-emits the stored PNG** as the same web-renderable payload the
original ``POST /generate`` response used (Requirement 12.9): the durable ``BYTEA``
bytes are re-encoded via :func:`app.codec.encode_image` into ``{mime_type,
data_base64}`` so a reopened history record renders identically without conversion.
"""

from __future__ import annotations

from typing import Any

from ai_shared.history import HistorySummary, ImageRecord, ProjectId

from .codec import encode_image

__all__ = ["summary_to_json", "record_to_json"]


def summary_to_json(summary: HistorySummary) -> dict[str, Any]:
    """Serialize a list-view summary (id, timestamp, short label = the prompt)."""
    return {
        "id": str(summary.id),
        "project_id": ProjectId.IMAGE.value,
        "created_at": summary.created_at.isoformat(),
        "label": summary.label,
    }


def record_to_json(record_id: str, record: ImageRecord) -> dict[str, Any]:
    """Serialize a full image record, re-emitting the stored PNG payload.

    Mirrors the persisted columns (Requirement 12.9): the prompt + model (inputs)
    and the generated image (output) re-encoded from the durable ``BYTEA`` bytes
    into the same web-renderable ``{mime_type, data_base64}`` payload the original
    response used, plus the creation timestamp. The frontend can render
    ``data:<mime_type>;base64,<data_base64>`` directly.
    """
    image = encode_image(record.image_bytes, record.mime_type)
    return {
        "id": record_id,
        "project_id": ProjectId.IMAGE.value,
        "created_at": record.created_at.isoformat(),
        "inputs": {
            "prompt": record.prompt,
            "model": record.model,
        },
        "outputs": {
            "mime_type": image.mime_type,
            "data_base64": image.data_base64,
        },
    }
