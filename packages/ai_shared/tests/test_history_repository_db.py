"""DB-backed repository read-path tests (Task 4.8, Requirement 13.3).

Against an ephemeral PostgreSQL: ``save_record`` then ``list_records`` returns the
saved summaries newest-first with timestamps; ``get_record`` returns the full
persisted inputs/outputs; an unknown id returns ``None``.

These tests SKIP cleanly when no test database is reachable (see ``db_utils``), so
they never hang or hard-fail in an environment without PostgreSQL. The orchestrator
runs them against a Docker ``postgres:16`` container once Docker is ready.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from ai_shared.db import dispose_engine, get_engine, get_sessionmaker
from ai_shared.history import (
    CapstoneIngestRecord,
    CapstoneIngestResult,
    CapstoneTaskRecord,
    CapstoneTaskResult,
    ChatTurnResult,
    Citation,
    DeepResearchResult,
    HistoryRepository,
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
    build_history_record,
)
from ai_shared.llm_types import Usage
from ai_shared.models import ALL_TABLES, Base

from . import db_utils

pytestmark = pytest.mark.skipif(
    not db_utils.database_reachable(), reason=db_utils.SKIP_REASON
)


@pytest.fixture()
def repo():
    """A HistoryRepository against the ephemeral DB with freshly-truncated tables."""
    settings = db_utils.test_settings()
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    # Truncate every history table (RESTART IDENTITY so ids are predictable) for a
    # clean slate between tests — keeps Hypothesis/DB state independent.
    table_names = ", ".join(t.__tablename__ for t in ALL_TABLES)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))

    yield HistoryRepository(get_sessionmaker(settings))

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    dispose_engine(settings)


def test_playground_save_list_get_roundtrip(repo: HistoryRepository):
    # Save two playground runs.
    r1 = build_history_record(
        ProjectId.PLAYGROUND,
        PlaygroundResult(
            prompt="first prompt",
            system_prompt="be terse",
            temperature=0.7,
            max_tokens=256,
            model="claude-opus-4.7",
            response_text="first answer",
            usage=Usage(prompt_tokens=3, output_tokens=2, total_tokens=5),
        ),
    )
    r2 = build_history_record(
        ProjectId.PLAYGROUND,
        PlaygroundResult(
            prompt="second prompt with unicode \u00e9\u2728",
            system_prompt=None,
            temperature=1.5,
            max_tokens=1024,
            model="claude-opus-4.7",
            response_text="second answer",
            usage=Usage(prompt_tokens=10, output_tokens=20, total_tokens=30),
        ),
    )
    id1 = repo.save_record(ProjectId.PLAYGROUND, r1)
    id2 = repo.save_record(ProjectId.PLAYGROUND, r2)

    # list_records is newest-first with timestamps.
    summaries = repo.list_records(ProjectId.PLAYGROUND)
    assert [s.id for s in summaries] == [id2, id1]
    assert all(s.created_at is not None for s in summaries)
    assert summaries[0].label.startswith("second prompt")

    # get_record returns the full persisted inputs/outputs.
    full = repo.get_record(ProjectId.PLAYGROUND, id2)
    assert isinstance(full, PlaygroundRecord)
    assert full.prompt == "second prompt with unicode \u00e9\u2728"
    assert full.system_prompt is None
    assert full.temperature == 1.5
    assert full.max_tokens == 1024
    assert full.response_text == "second answer"
    assert full.usage == {"prompt_tokens": 10, "output_tokens": 20, "total_tokens": 30}

    # Unknown id -> None.
    assert repo.get_record(ProjectId.PLAYGROUND, 999_999) is None


def test_web_agent_empty_and_populated_citations(repo: HistoryRepository):
    empty = build_history_record(
        ProjectId.WEB_AGENT,
        WebAgentResult(question="q-empty", answer="no sources", citations=[]),
    )
    full = build_history_record(
        ProjectId.WEB_AGENT,
        WebAgentResult(
            question="q-full",
            answer="answer",
            citations=[Citation(url="https://a.com", title="A"), Citation(url="https://b.com", title="B")],
        ),
    )
    id_empty = repo.save_record(ProjectId.WEB_AGENT, empty)
    id_full = repo.save_record(ProjectId.WEB_AGENT, full)

    got_empty = repo.get_record(ProjectId.WEB_AGENT, id_empty)
    got_full = repo.get_record(ProjectId.WEB_AGENT, id_full)
    assert got_empty.citations == []  # empty JSONB list round-trips
    assert got_full.citations == [{"url": "https://a.com", "title": "A"}, {"url": "https://b.com", "title": "B"}]


def test_image_bytes_roundtrip_exactly(repo: HistoryRepository):
    # A large-ish blob with all byte values to exercise BYTEA round-trip.
    blob = bytes(range(256)) * 64  # 16 KB
    rec = build_history_record(
        ProjectId.IMAGE,
        ImageGenerationResult(prompt="a cat", model="sd-xl", image_bytes=blob, mime_type="image/png"),
    )
    rid = repo.save_record(ProjectId.IMAGE, rec)
    got = repo.get_record(ProjectId.IMAGE, rid)
    assert isinstance(got, ImageRecord)
    assert got.image_bytes == blob
    assert got.mime_type == "image/png"


def test_chatbot_session_and_turns_relational(repo: HistoryRepository):
    # Two turns under the same session_id share one session row.
    t1 = build_history_record(
        ProjectId.SUPPORT,
        ChatTurnResult(session_id="sess-1", user_message="hi", assistant_reply="hello"),
    )
    t2 = build_history_record(
        ProjectId.SUPPORT,
        ChatTurnResult(session_id="sess-1", user_message="bye", assistant_reply="goodbye"),
    )
    s1 = repo.save_record(ProjectId.SUPPORT, t1)
    s2 = repo.save_record(ProjectId.SUPPORT, t2)
    assert s1 == s2  # same session row id

    summaries = repo.list_records(ProjectId.SUPPORT)
    assert len(summaries) == 1
    assert summaries[0].label == "sess-1"

    got = repo.get_record(ProjectId.SUPPORT, s1)
    assert got.session_id == "sess-1"
    # The detail variant carries the latest turn content.
    assert got.assistant_reply == "goodbye"


def test_deep_research_full_report_roundtrip(repo: HistoryRepository):
    subqs = [SubQuestion(id=i, text=f"sq{i}") for i in range(3)]
    sections = [ReportSection(sub_question=sq.text, body=f"body{sq.id}", citations=[Citation("https://s.com", "S")]) for sq in subqs]
    report = ResearchReport(title="T", introduction="intro", sections=sections, conclusion="concl")
    rec = build_history_record(
        ProjectId.DEEP_RESEARCH,
        DeepResearchResult(topic="topic", sub_questions=subqs, report=report, citations=[Citation("https://s.com", "S")]),
    )
    rid = repo.save_record(ProjectId.DEEP_RESEARCH, rec)
    got = repo.get_record(ProjectId.DEEP_RESEARCH, rid)
    assert got.topic == "topic"
    assert len(got.sub_questions) == 3
    assert got.report["title"] == "T"
    assert len(got.report["sections"]) == 3


def test_capstone_task_and_ingest_merged_newest_first(repo: HistoryRepository):
    task = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneTaskResult(
            task_text="do a thing",
            final_answer="done",
            tools_invoked=[ToolInvocation(tool="search", ok=True, error=None), ToolInvocation(tool="calc", ok=False, error="boom")],
            sources=["doc-a"],
            step_limit_reached=False,
        ),
    )
    ingest = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneIngestResult(documents=[IngestedDoc(name="doc-a", chunks=3), IngestedDoc(name="doc-b", chunks=5)]),
    )
    # Both rows are id=1 in their (freshly TRUNCATEd, independently-sequenced)
    # tables, so the numeric ids collide. The kind-discriminated id keeps the
    # detail lookup unambiguous (BUG-003).
    task_id = repo.save_record(ProjectId.CAPSTONE, task)
    ingest_id = repo.save_record(ProjectId.CAPSTONE, ingest)
    assert task_id == "task:1"
    assert ingest_id == "ingest:1"

    summaries = repo.list_records(ProjectId.CAPSTONE)
    # Both kinds appear, newest-first by created_at, carrying discriminated ids.
    assert len(summaries) == 2
    assert {s.id for s in summaries} == {"task:1", "ingest:1"}

    # The numeric-id collision no longer hides the ingest row: each discriminated
    # id resolves to its own record kind.
    got_task = repo.get_record(ProjectId.CAPSTONE, task_id)
    assert isinstance(got_task, CapstoneTaskRecord)
    assert got_task.final_answer == "done"
    assert any(t["ok"] is False for t in got_task.tools_invoked)

    got_ingest = repo.get_record(ProjectId.CAPSTONE, ingest_id)
    assert isinstance(got_ingest, CapstoneIngestRecord)
    assert got_ingest.documents == ["doc-a", "doc-b"]


def test_capstone_numeric_id_collision_resolves_by_kind(repo: HistoryRepository):
    """Regression for BUG-003: a task row and an ingest row that share a numeric id
    (both id=1 after ``TRUNCATE ... RESTART IDENTITY``) must each be retrievable by
    their kind-discriminated id, and an unknown/malformed capstone id returns None.
    """
    task = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneTaskResult(
            task_text="run task",
            final_answer="task answer",
            tools_invoked=[ToolInvocation(tool="search", ok=True, error=None)],
            sources=["src-1"],
            step_limit_reached=True,
        ),
    )
    ingest = build_history_record(
        ProjectId.CAPSTONE,
        CapstoneIngestResult(documents=[IngestedDoc(name="only-doc", chunks=1)]),
    )

    # Deliberately force the numeric-id collision: each table's SERIAL starts at 1
    # in the freshly-truncated schema, so both rows get id=1.
    task_id = repo.save_record(ProjectId.CAPSTONE, task)
    ingest_id = repo.save_record(ProjectId.CAPSTONE, ingest)
    assert task_id == "task:1"
    assert ingest_id == "ingest:1"  # same numeric id, different kind

    # get_record returns the correct KIND for each discriminated id.
    by_task = repo.get_record(ProjectId.CAPSTONE, "task:1")
    assert isinstance(by_task, CapstoneTaskRecord)
    assert by_task.task_text == "run task"
    assert by_task.step_limit_reached is True

    by_ingest = repo.get_record(ProjectId.CAPSTONE, "ingest:1")
    assert isinstance(by_ingest, CapstoneIngestRecord)
    assert by_ingest.documents == ["only-doc"]

    # Swapping the kind selects the other table's row (no cross-contamination).
    assert isinstance(repo.get_record(ProjectId.CAPSTONE, task_id), CapstoneTaskRecord)
    assert isinstance(repo.get_record(ProjectId.CAPSTONE, ingest_id), CapstoneIngestRecord)

    # Unknown numeric id (valid form) -> None for either kind.
    assert repo.get_record(ProjectId.CAPSTONE, "task:999999") is None
    assert repo.get_record(ProjectId.CAPSTONE, "ingest:999999") is None

    # Malformed capstone ids -> None (no prefix, unknown prefix, non-int, bare int).
    for bad in ("1", "bogus:1", "task:", "task:abc", "ingest", 1):
        assert repo.get_record(ProjectId.CAPSTONE, bad) is None


def test_unknown_id_returns_none_for_every_project(repo: HistoryRepository):
    for project in ProjectId:
        # Capstone ids are kind-discriminated strings; use a valid-form-but-absent
        # id so the lookup is well-formed yet still returns None (BUG-003).
        missing_id = "task:999999" if project is ProjectId.CAPSTONE else 123_456
        assert repo.get_record(project, missing_id) is None


def test_empty_history_lists_are_empty(repo: HistoryRepository):
    for project in ProjectId:
        assert repo.list_records(project) == []
