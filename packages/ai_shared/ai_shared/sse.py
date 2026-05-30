"""Server-Sent Events (SSE) formatting helpers (Requirement 3.10).

These pure, deterministic helpers serialize the shared streaming vocabulary
(``data`` / ``progress`` / ``done`` / ``error``) into ``text/event-stream`` frames
so every backend that streams a response uses one identical wire format. The
frontend SSE client (``apps/web/src/lib/api.ts``) buffers the byte stream, splits
frames on blank lines, and parses the ``event:`` / ``data:`` lines this module
produces.

Frame shape (one event)::

    event: <type>\\n
    data: <json>\\n
    \\n

The ``data`` payload is always a single-line JSON object (``json.dumps`` with no
embedded newlines, ``ensure_ascii=False`` so unicode is preserved as UTF-8). A
trailing blank line terminates the frame. :func:`parse_sse_frame` is the inverse
of :func:`format_sse` for a single well-formed frame and is used by the round-trip
tests.
"""

from __future__ import annotations

import json
from typing import Any

from .llm_types import EventType, StreamEvent

__all__ = [
    "format_sse",
    "format_event",
    "format_data",
    "format_progress",
    "format_done",
    "format_error",
    "parse_sse_frame",
]


def _encode_data(data: dict[str, Any]) -> str:
    """JSON-encode an event payload onto a single line.

    ``separators`` is compact and ``ensure_ascii=False`` keeps unicode readable in
    the stream. The result is guaranteed newline-free because ``json.dumps``
    escapes any newline inside string values as ``\\n``.
    """
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def format_sse(event_type: EventType, data: dict[str, Any] | None = None) -> str:
    """Format one SSE frame for ``event_type`` carrying ``data``.

    Produces ``event: <type>\\ndata: <json>\\n\\n``. ``data`` defaults to an empty
    object so an absent payload still serializes to valid JSON (``{}``).
    """
    payload = _encode_data(data if data is not None else {})
    return f"event: {event_type}\ndata: {payload}\n\n"


def format_event(event: StreamEvent) -> str:
    """Serialize a :class:`StreamEvent` to its SSE frame."""
    return format_sse(event.type, event.data)


def format_data(text: str) -> str:
    """Frame an incremental content chunk as a ``data`` event (``{"text": ...}``)."""
    return format_sse("data", {"text": text})


def format_progress(phase: str, step: int, **extra: Any) -> str:
    """Frame a step update as a ``progress`` event (``{"phase", "step", ...}``)."""
    return format_sse("progress", {"phase": phase, "step": step, **extra})


def format_done(**data: Any) -> str:
    """Frame the terminal success ``done`` event (optionally carrying metadata)."""
    return format_sse("done", dict(data))


def format_error(action: str, reason: str, **extra: Any) -> str:
    """Frame the terminal failure ``error`` event (``{"action", "reason", ...}``)."""
    return format_sse("error", {"action": action, "reason": reason, **extra})


def parse_sse_frame(frame: str) -> tuple[str, dict[str, Any]]:
    """Parse a single well-formed SSE frame back to ``(event_type, data)``.

    Inverse of :func:`format_sse` for one frame: reads the ``event:`` line and the
    ``data:`` line (JSON-decoding the payload). Leading/trailing blank lines are
    ignored. Raises :class:`ValueError` if either required line is absent.
    """
    event_type: str | None = None
    data_payload: dict[str, Any] | None = None

    for line in frame.split("\n"):
        if not line.strip():
            continue
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_payload = json.loads(line[len("data:") :].strip())

    if event_type is None:
        raise ValueError("SSE frame is missing an 'event:' line")
    if data_payload is None:
        raise ValueError("SSE frame is missing a 'data:' line")
    return event_type, data_payload
