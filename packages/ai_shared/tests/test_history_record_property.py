"""Property-based test for ``build_history_record`` (Property 33).

# Feature: ai-engineer-practice-monorepo, Property 33: per project type the constructed History_Record contains exactly the required fields plus a timestamp

**Validates: Requirements 12.1, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 12.11**

For every mini-project type and any valid completed-operation result, the
constructed :data:`HistoryRecord` contains **exactly** the fields required for that
project type (per Requirements 12.5–12.11) **plus** a creation timestamp, and no
required field is missing. ``build_history_record`` is pure, so this test needs no
database connection.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

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
    WebAgentResult,
    WebAgentRecord,
    build_history_record,
)
from ai_shared.llm_types import Usage

# Exactly the fields required per project type (Requirements 12.5–12.11), each
# PLUS the creation timestamp ``created_at`` (Requirement 12.1).
EXPECTED_FIELDS: dict[str, set[str]] = {
    "playground": {
        "prompt",
        "system_prompt",
        "temperature",
        "max_tokens",
        "model",
        "response_text",
        "usage",
        "created_at",
    },
    "support": {"session_id", "user_message", "assistant_reply", "created_at"},
    "web-agent": {"question", "answer", "citations", "created_at"},
    "deep-research": {"topic", "sub_questions", "report", "citations", "created_at"},
    "image": {"prompt", "model", "image_bytes", "mime_type", "created_at"},
    "capstone-task": {
        "task_text",
        "final_answer",
        "tools_invoked",
        "sources",
        "step_limit_reached",
        "created_at",
    },
    "capstone-ingest": {"documents", "created_at"},
}

# ---- generators ---------------------------------------------------------- #
_text = st.text(min_size=0, max_size=40)
_nonneg = st.integers(min_value=0, max_value=10_000)


@st.composite
def usages(draw) -> Usage:
    p = draw(_nonneg)
    o = draw(_nonneg)
    return Usage(prompt_tokens=p, output_tokens=o, total_tokens=p + o)


@st.composite
def citations(draw) -> Citation:
    return Citation(url="https://ex.com/" + draw(_text), title=draw(_text))


@st.composite
def playground_results(draw) -> PlaygroundResult:
    has_system = draw(st.booleans())
    return PlaygroundResult(
        prompt=draw(st.text(min_size=1, max_size=80)),
        system_prompt=draw(_text) if has_system else None,
        temperature=draw(st.floats(min_value=0.0, max_value=2.0)),
        max_tokens=draw(st.integers(min_value=1, max_value=4096)),
        model=draw(st.text(min_size=1, max_size=30)),
        response_text=draw(_text),
        usage=draw(usages()),
    )


@st.composite
def chat_results(draw) -> ChatTurnResult:
    return ChatTurnResult(
        session_id=draw(st.text(min_size=1, max_size=40)),
        user_message=draw(st.text(min_size=1, max_size=80)),
        assistant_reply=draw(_text),
    )


@st.composite
def web_results(draw) -> WebAgentResult:
    return WebAgentResult(
        question=draw(st.text(min_size=1, max_size=80)),
        answer=draw(_text),
        citations=draw(st.lists(citations(), min_size=0, max_size=5)),
    )


@st.composite
def research_results(draw) -> DeepResearchResult:
    n = draw(st.integers(min_value=3, max_value=10))
    subqs = [SubQuestion(id=i, text=draw(_text)) for i in range(n)]
    sections = [
        ReportSection(
            sub_question=sq.text,
            body=draw(_text),
            citations=draw(st.lists(citations(), min_size=0, max_size=3)),
        )
        for sq in subqs
    ]
    report = ResearchReport(
        title=draw(st.text(min_size=1, max_size=40)),
        introduction=draw(_text),
        sections=sections,
        conclusion=draw(_text),
    )
    return DeepResearchResult(
        topic=draw(st.text(min_size=1, max_size=60)),
        sub_questions=subqs,
        report=report,
        citations=draw(st.lists(citations(), min_size=0, max_size=5)),
    )


@st.composite
def image_results(draw) -> ImageGenerationResult:
    return ImageGenerationResult(
        prompt=draw(st.text(min_size=1, max_size=60)),
        model=draw(st.text(min_size=1, max_size=30)),
        image_bytes=draw(st.binary(min_size=0, max_size=512)),
        mime_type=draw(st.sampled_from(["image/png", "image/jpeg", "image/webp"])),
    )


@st.composite
def capstone_task_results(draw) -> CapstoneTaskResult:
    tools = draw(
        st.lists(
            st.builds(
                ToolInvocation,
                tool=st.text(min_size=1, max_size=20),
                ok=st.booleans(),
                error=st.none() | _text,
            ),
            min_size=0,
            max_size=5,
        )
    )
    return CapstoneTaskResult(
        task_text=draw(st.text(min_size=1, max_size=80)),
        final_answer=draw(_text),
        tools_invoked=tools,
        sources=draw(st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=5)),
        step_limit_reached=draw(st.booleans()),
    )


@st.composite
def capstone_ingest_results(draw) -> CapstoneIngestResult:
    docs = draw(
        st.lists(
            st.builds(IngestedDoc, name=st.text(min_size=1, max_size=20), chunks=_nonneg),
            min_size=1,
            max_size=5,
        )
    )
    return CapstoneIngestResult(documents=docs)


def _field_names(record) -> set[str]:
    return {f.name for f in dataclasses.fields(record)}


@settings(max_examples=200, deadline=None)
@given(
    case=st.one_of(
        st.tuples(st.just(ProjectId.PLAYGROUND), st.just("playground"), playground_results()),
        st.tuples(st.just(ProjectId.SUPPORT), st.just("support"), chat_results()),
        st.tuples(st.just(ProjectId.WEB_AGENT), st.just("web-agent"), web_results()),
        st.tuples(st.just(ProjectId.DEEP_RESEARCH), st.just("deep-research"), research_results()),
        st.tuples(st.just(ProjectId.IMAGE), st.just("image"), image_results()),
        st.tuples(st.just(ProjectId.CAPSTONE), st.just("capstone-task"), capstone_task_results()),
        st.tuples(st.just(ProjectId.CAPSTONE), st.just("capstone-ingest"), capstone_ingest_results()),
    )
)
def test_build_history_record_has_exactly_required_fields_plus_timestamp(case):
    project, key, result = case
    record = build_history_record(project, result)

    # 1) The record carries EXACTLY the required fields for this project type
    #    plus a creation timestamp — none missing, none extra.
    assert _field_names(record) == EXPECTED_FIELDS[key]

    # 2) The creation timestamp is present and is a datetime (Requirement 12.1).
    assert isinstance(record.created_at, datetime)

    # 3) No required field is missing/None where the requirement mandates a value.
    #    (system_prompt is the only optional field — Requirement 12.5.)
    for name in EXPECTED_FIELDS[key]:
        value = getattr(record, name)
        if name == "system_prompt":
            continue
        assert value is not None, f"{key}.{name} must not be missing"

    # 4) Spot-check that the values were faithfully carried from the result and
    #    that structured sub-objects were normalized to JSON-able shapes.
    if isinstance(record, PlaygroundRecord):
        assert record.prompt == result.prompt
        assert record.usage == result.usage.to_dict()
    elif isinstance(record, ChatTurnRecord):
        assert record.session_id == result.session_id
    elif isinstance(record, WebAgentRecord):
        assert record.citations == [c.to_json() for c in result.citations]
    elif isinstance(record, DeepResearchRecord):
        assert len(record.report["sections"]) == len(result.sub_questions)
    elif isinstance(record, ImageRecord):
        assert record.image_bytes == result.image_bytes
        assert record.mime_type == result.mime_type
    elif isinstance(record, CapstoneTaskRecord):
        assert record.step_limit_reached == result.step_limit_reached
        assert all(set(t.keys()) == {"tool", "ok", "error"} for t in record.tools_invoked)
    elif isinstance(record, CapstoneIngestRecord):
        assert record.documents == [d.name for d in result.documents]


@settings(max_examples=100, deadline=None)
@given(ts=st.datetimes(timezones=st.just(timezone.utc)), result=playground_results())
def test_build_history_record_honors_explicit_timestamp(ts: datetime, result: PlaygroundResult):
    """An explicitly supplied creation timestamp is used verbatim."""
    record = build_history_record(ProjectId.PLAYGROUND, result, created_at=ts)
    assert record.created_at == ts
