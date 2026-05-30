"""Unit tests for ``ai_shared.sse`` event formatting (Requirement 3.10).

Each event type (``data`` / ``progress`` / ``done`` / ``error``) must serialize to
a ``text/event-stream`` frame that round-trips: parsing the ``event:`` / ``data:``
lines back yields the original event type and JSON payload. Edge cases covered:
empty payload, unicode content, multi-line content, and special characters.
"""

from __future__ import annotations

import json

import pytest

from ai_shared.llm_types import StreamEvent
from ai_shared.sse import (
    format_data,
    format_done,
    format_error,
    format_event,
    format_progress,
    format_sse,
    parse_sse_frame,
)


def _assert_frame_shape(frame: str) -> None:
    """A well-formed frame has an ``event:`` line, a ``data:`` line, blank-line end."""
    assert frame.startswith("event: ")
    assert "\ndata: " in frame
    assert frame.endswith("\n\n")
    # The data payload occupies exactly one line (no raw newlines inside it).
    data_line = frame.split("\ndata: ", 1)[1].rstrip("\n")
    assert "\n" not in data_line


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("data", {"text": "hello world"}),
        ("progress", {"phase": "search", "step": 3}),
        ("done", {"usage": {"prompt_tokens": 5, "output_tokens": 7, "total_tokens": 12}}),
        ("error", {"action": "generate", "reason": "gateway timed out"}),
    ],
)
def test_each_event_type_round_trips(event_type: str, payload: dict) -> None:
    """Every event type serializes to a frame that parses back to (type, payload)."""
    frame = format_sse(event_type, payload)
    _assert_frame_shape(frame)
    parsed_type, parsed_data = parse_sse_frame(frame)
    assert parsed_type == event_type
    assert parsed_data == payload


def test_empty_data_dict_round_trips() -> None:
    """An empty payload serializes to ``{}`` and parses back to an empty dict."""
    frame = format_sse("done", {})
    assert "data: {}" in frame
    parsed_type, parsed_data = parse_sse_frame(frame)
    assert parsed_type == "done"
    assert parsed_data == {}


def test_absent_data_defaults_to_empty_object() -> None:
    """Omitting the payload entirely still yields valid JSON (``{}``)."""
    frame = format_sse("done")
    parsed_type, parsed_data = parse_sse_frame(frame)
    assert parsed_type == "done"
    assert parsed_data == {}


def test_unicode_content_round_trips() -> None:
    """Unicode (emoji, accents, CJK) survives the round-trip exactly."""
    payload = {"text": "héllo 🌍 世界 — naïve café"}
    frame = format_sse("data", payload)
    _assert_frame_shape(frame)
    # ensure_ascii=False keeps the unicode readable in the stream (not \\uXXXX).
    assert "🌍" in frame
    _, parsed_data = parse_sse_frame(frame)
    assert parsed_data == payload


def test_multiline_content_is_escaped_and_round_trips() -> None:
    """Multi-line content is JSON-escaped to one line and decodes to the original.

    The SSE frame format is line-oriented, so embedded newlines MUST be escaped
    (as ``\\n``) inside the JSON payload to avoid breaking frame parsing.
    """
    payload = {"text": "line one\nline two\r\nline three\ttabbed"}
    frame = format_sse("data", payload)
    _assert_frame_shape(frame)  # asserts the data line has no raw newline
    _, parsed_data = parse_sse_frame(frame)
    assert parsed_data == payload


def test_special_characters_round_trip() -> None:
    """Quotes, backslashes, and colons inside values survive the round-trip."""
    payload = {"reason": 'he said "boom": c:\\path\\to\\thing, a:b'}
    frame = format_sse("error", payload)
    _, parsed_data = parse_sse_frame(frame)
    assert parsed_data == payload


def test_format_event_matches_format_sse() -> None:
    """``format_event(StreamEvent)`` equals ``format_sse(type, data)``."""
    event = StreamEvent(type="progress", data={"phase": "synthesis", "step": 9})
    assert format_event(event) == format_sse("progress", {"phase": "synthesis", "step": 9})


def test_typed_helpers_produce_expected_payloads() -> None:
    """The convenience helpers frame the documented payload shapes."""
    _, data = parse_sse_frame(format_data("tok"))
    assert data == {"text": "tok"}

    _, prog = parse_sse_frame(format_progress("search", 2, sub_question="q1"))
    assert prog == {"phase": "search", "step": 2, "sub_question": "q1"}

    _, done = parse_sse_frame(format_done(usage={"total_tokens": 3}))
    assert done == {"usage": {"total_tokens": 3}}

    _, err = parse_sse_frame(format_error("ask", "search failed", citations=[]))
    assert err == {"action": "ask", "reason": "search failed", "citations": []}


def test_parse_rejects_frame_missing_event_line() -> None:
    """A frame with no ``event:`` line is rejected (defensive parsing)."""
    with pytest.raises(ValueError):
        parse_sse_frame("data: {}\n\n")


def test_parse_rejects_frame_missing_data_line() -> None:
    """A frame with no ``data:`` line is rejected (defensive parsing)."""
    with pytest.raises(ValueError):
        parse_sse_frame("event: done\n\n")


def test_data_payload_is_compact_single_line_json() -> None:
    """The serialized payload is compact JSON and contains no spaces after colons."""
    frame = format_sse("progress", {"phase": "x", "step": 1})
    data_line = frame.split("\ndata: ", 1)[1].rstrip("\n")
    # Compact separators => valid JSON and a stable, single-line representation.
    assert json.loads(data_line) == {"phase": "x", "step": 1}
    assert ", " not in data_line and ": " not in data_line
