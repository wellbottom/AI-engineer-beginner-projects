"""Regression unit tests for NUL-byte sanitization in ``build_history_record``
(BUG-006).

PostgreSQL ``text``/``varchar`` columns cannot store the NUL byte (``\\x00``):
persisting one raises ``psycopg.DataError`` ("PostgreSQL text fields cannot contain
NUL (0x00) bytes"). User-supplied text reaches durable history through every
service, so the failure is cross-cutting. :func:`build_history_record` therefore
strips ``\\x00`` from every persisted TEXT field (and from strings nested in the
JSON-able payloads) at record construction, keeping durable history intact
("keep everything", Requirement 12.2) instead of dropping records via the
best-effort write wrapper (Requirement 12.4). Image BYTEA legitimately holds
``0x00`` and is deliberately left untouched.

These are plain example-based unit tests (not one of the 36 correctness
properties). They assert:

- ``\\x00`` is stripped from representative TEXT fields across project types, and
- normal (non-NUL) text round-trips byte-for-byte unchanged, and
- image bytes (BYTEA) keep their ``0x00`` bytes intact.
"""

from __future__ import annotations

from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneIngestResult,
    CapstoneTaskRecord,
    CapstoneTaskResult,
    ChatTurnRecord,
    ChatTurnResult,
    Citation,
    DeepResearchRecord,
    DeepResearchResult,
    ImageGenerationResult,
    ImageRecord,
    IngestedDoc,
    PlaygroundRecord,
    PlaygroundResult,
    ProjectId,
    ReportSection,
    ResearchReport,
    SubQuestion,
    ToolInvocation,
    WebAgentRecord,
    WebAgentResult,
    _strip_nul,
    build_history_record,
)
from ai_shared.llm_types import Usage


def _has_nul(value) -> bool:
    """Recursively detect any ``\\x00`` inside a string / JSON-able structure."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


# --------------------------------------------------------------------------- #
# Pure helper.
# --------------------------------------------------------------------------- #
def test_strip_nul_removes_nul_and_is_noop_for_normal_text():
    assert _strip_nul("\x00") == ""
    assert _strip_nul("a\x00b\x00c") == "abc"
    assert _strip_nul("\x00lead") == "lead"
    assert _strip_nul("trail\x00") == "trail"
    # Normal text (incl. unicode) is returned byte-for-byte unchanged.
    for normal in ["", "hello", "unicode \u00e9\u2728\U0001f600", "tabs\tand\nnewlines"]:
        assert _strip_nul(normal) == normal


# --------------------------------------------------------------------------- #
# Per-project sanitization (the counterexample byte + representative fields).
# --------------------------------------------------------------------------- #
def test_playground_strips_nul_from_prompt_and_response():
    rec = build_history_record(
        ProjectId.PLAYGROUND,
        PlaygroundResult(
            prompt="pro\x00mpt",
            system_prompt="sys\x00tem",
            temperature=0.5,
            max_tokens=128,
            model="claude\x00-opus",
            response_text="resp\x00onse",
            usage=Usage(prompt_tokens=1, output_tokens=2, total_tokens=3),
        ),
    )
    assert isinstance(rec, PlaygroundRecord)
    assert rec.prompt == "prompt"
    assert rec.system_prompt == "system"
    assert rec.model == "claude-opus"
    assert rec.response_text == "response"


def test_playground_optional_system_prompt_none_is_preserved():
    rec = build_history_record(
        ProjectId.PLAYGROUND,
        PlaygroundResult(
            prompt="p",
            system_prompt=None,
            temperature=0.0,
            max_tokens=1,
            model="m",
            response_text="r",
            usage=Usage(prompt_tokens=0, output_tokens=0, total_tokens=0),
        ),
    )
    assert rec.system_prompt is None


def test_chatbot_strips_nul_from_user_message_and_assistant_reply():
    # The exact Property 36 counterexample: assistant_reply == "\x00".
    rec = build_history_record(
        ProjectId.SUPPORT,
        ChatTurnResult(session_id="sess\x00", user_message="0", assistant_reply="\x00"),
    )
    assert isinstance(rec, ChatTurnRecord)
    assert rec.session_id == "sess"
    assert rec.user_message == "0"
    assert rec.assistant_reply == ""


def test_web_agent_strips_nul_from_answer_and_citation_title():
    rec = build_history_record(
        ProjectId.WEB_AGENT,
        WebAgentResult(
            question="q\x00uestion",
            answer="ans\x00wer",
            citations=[Citation(url="https://ex.com/a\x00b", title="Ti\x00tle")],
        ),
    )
    assert isinstance(rec, WebAgentRecord)
    assert rec.question == "question"
    assert rec.answer == "answer"
    assert rec.citations == [{"url": "https://ex.com/ab", "title": "Title"}]
    assert not _has_nul(rec.citations)


def test_deep_research_strips_nul_from_report_body_and_nested_text():
    subqs = [SubQuestion(id=0, text="sq\x00")]
    sections = [
        ReportSection(
            sub_question="sq\x00",
            body="bo\x00dy",
            citations=[Citation(url="https://s.com", title="S\x00")],
        )
    ]
    report = ResearchReport(
        title="ti\x00tle",
        introduction="in\x00tro",
        sections=sections,
        conclusion="con\x00cl",
    )
    rec = build_history_record(
        ProjectId.DEEP_RESEARCH,
        DeepResearchResult(
            topic="top\x00ic",
            sub_questions=subqs,
            report=report,
            citations=[Citation(url="https://s.com", title="C\x00")],
        ),
    )
    assert isinstance(rec, DeepResearchRecord)
    assert rec.topic == "topic"
    assert rec.report["title"] == "title"
    assert rec.report["introduction"] == "intro"
    assert rec.report["conclusion"] == "concl"
    assert rec.report["sections"][0]["body"] == "body"
    # No NUL survives anywhere in the normalized JSON payloads.
    assert not _has_nul(rec.report)
    assert not _has_nul(rec.sub_questions)
    assert not _has_nul(rec.citations)


def test_capstone_task_strips_nul_from_task_text_tool_error_and_sources():
    rec = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneTaskResult(
            task_text="ta\x00sk",
            final_answer="ans\x00wer",
            tools_invoked=[ToolInvocation(tool="sea\x00rch", ok=False, error="bo\x00om")],
            sources=["src\x00-1", "src-2"],
            step_limit_reached=True,
        ),
    )
    assert isinstance(rec, CapstoneTaskRecord)
    assert rec.task_text == "task"
    assert rec.final_answer == "answer"
    assert rec.tools_invoked[0]["tool"] == "search"
    assert rec.tools_invoked[0]["error"] == "boom"
    assert rec.sources == ["src-1", "src-2"]
    assert not _has_nul(rec.tools_invoked)


def test_capstone_ingest_strips_nul_from_document_name():
    rec = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneIngestResult(documents=[IngestedDoc(name="do\x00c.pdf", chunks=3)]),
    )
    assert isinstance(rec, CapstoneIngestRecord)
    assert rec.documents == ["doc.pdf"]


# --------------------------------------------------------------------------- #
# Non-NUL text and image BYTEA are left untouched.
# --------------------------------------------------------------------------- #
def test_normal_text_round_trips_unchanged():
    rec = build_history_record(
        ProjectId.SUPPORT,
        ChatTurnResult(
            session_id="sess-1",
            user_message="hello there",
            assistant_reply="general unicode \u00e9\u2728",
        ),
    )
    assert rec.session_id == "sess-1"
    assert rec.user_message == "hello there"
    assert rec.assistant_reply == "general unicode \u00e9\u2728"


def test_image_bytes_with_nul_are_not_sanitized():
    # BYTEA legitimately holds 0x00; image bytes must survive byte-for-byte.
    blob = bytes(range(256))  # includes 0x00
    rec = build_history_record(
        ProjectId.IMAGE,
        ImageGenerationResult(
            prompt="a ca\x00t",  # prompt text IS sanitized
            model="sd\x00-xl",
            image_bytes=blob,
            mime_type="image/png",
        ),
    )
    assert isinstance(rec, ImageRecord)
    assert rec.prompt == "a cat"  # text sanitized
    assert rec.model == "sd-xl"
    assert rec.image_bytes == blob  # bytes untouched, 0x00 preserved
    assert b"\x00" in rec.image_bytes
