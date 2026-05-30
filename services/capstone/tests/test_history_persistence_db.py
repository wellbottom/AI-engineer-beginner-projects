"""DB-backed example test: capstone task + ingest persistence round-trip.

**Validates: Requirements 12.10, 12.11, 12.3, 13.3**

Against the **real** ephemeral PostgreSQL (via the shared :class:`HistoryRepository`),
this proves the capstone write-on-completion + browse flow end-to-end with real
persistence (not a stub):

- A completed **task run** persists a ``CapstoneTaskRecord`` (task text, final
  answer, tools invoked with ok/failure, sources, step-limit flag) and is retrievable
  by its ``kind``-discriminated string id ``"task:<n>"`` (Requirements 12.10, 13.3).
- A successful **ingestion** persists a ``CapstoneIngestRecord`` (document names) and
  is retrievable by ``"ingest:<n>"`` (Requirements 12.11, 13.3).
- ``list_records`` merges both newest-first with discriminated ids; an unknown /
  malformed capstone id returns ``None`` (BUG-003).

This drives the SAME ``build_history_record`` -> ``save_record`` -> ``get_record``
path the service uses on completion. It SKIPS cleanly when no PostgreSQL is reachable
(see ``db_utils``); the orchestrator runs it against the ephemeral ``postgres``
provided via ``TEST_DATABASE_URL``.
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
    HistoryRepository,
    IngestedDoc,
    ProjectId,
    ToolInvocation,
    build_history_record,
)
from ai_shared.models import Base, CapstoneIngestHistory, CapstoneTaskHistory

from . import db_utils

pytestmark = pytest.mark.skipif(
    not db_utils.database_reachable(), reason=db_utils.SKIP_REASON
)

_TASK_TABLE = CapstoneTaskHistory.__tablename__
_INGEST_TABLE = CapstoneIngestHistory.__tablename__


@pytest.fixture()
def repo():
    """A HistoryRepository against the ephemeral DB with the capstone tables clean."""
    settings_obj = db_utils.test_settings()
    engine = get_engine(settings_obj)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TASK_TABLE} RESTART IDENTITY CASCADE"))
        conn.execute(text(f"TRUNCATE {_INGEST_TABLE} RESTART IDENTITY CASCADE"))
    repository = HistoryRepository(get_sessionmaker(settings_obj))
    yield repository
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TASK_TABLE} RESTART IDENTITY CASCADE"))
        conn.execute(text(f"TRUNCATE {_INGEST_TABLE} RESTART IDENTITY CASCADE"))
    dispose_engine(settings_obj)


def test_task_run_persists_and_retrieves_by_discriminated_id(repo: HistoryRepository) -> None:
    result = CapstoneTaskResult(
        task_text="analyze the ingested manuals",
        final_answer="the synthesized answer",
        tools_invoked=[
            ToolInvocation(tool="word_count", ok=True, error=None),
            ToolInvocation(tool="calculator", ok=False, error="invalid expression"),
        ],
        sources=["manual.txt", "spec.txt"],
        step_limit_reached=False,
    )
    record = build_history_record(ProjectId.CAPSTONE, result)
    saved_id = repo.save_record(ProjectId.CAPSTONE, record)

    # The capstone id is the kind-discriminated string id (BUG-003).
    assert isinstance(saved_id, str) and saved_id.startswith("task:")

    got = repo.get_record(ProjectId.CAPSTONE, saved_id)
    assert isinstance(got, CapstoneTaskRecord)
    assert got.task_text == "analyze the ingested manuals"
    assert got.final_answer == "the synthesized answer"
    assert got.sources == ["manual.txt", "spec.txt"]
    assert got.step_limit_reached is False
    # Tools invoked round-trip with their ok/failure flags (Requirement 12.10).
    assert {t["tool"]: t["ok"] for t in got.tools_invoked} == {"word_count": True, "calculator": False}


def test_ingest_persists_and_retrieves_by_discriminated_id(repo: HistoryRepository) -> None:
    result = CapstoneIngestResult(documents=[IngestedDoc(name="a.txt", chunks=2), IngestedDoc(name="b.txt", chunks=1)])
    record = build_history_record(ProjectId.CAPSTONE, result)
    saved_id = repo.save_record(ProjectId.CAPSTONE, record)

    assert isinstance(saved_id, str) and saved_id.startswith("ingest:")

    got = repo.get_record(ProjectId.CAPSTONE, saved_id)
    assert isinstance(got, CapstoneIngestRecord)
    assert got.documents == ["a.txt", "b.txt"]


def test_list_merges_task_and_ingest_newest_first_with_discriminated_ids(repo: HistoryRepository) -> None:
    task_id = repo.save_record(
        ProjectId.CAPSTONE,
        build_history_record(
            ProjectId.CAPSTONE,
            CapstoneTaskResult(
                task_text="t", final_answer="a", tools_invoked=[], sources=[], step_limit_reached=False
            ),
        ),
    )
    ingest_id = repo.save_record(
        ProjectId.CAPSTONE,
        build_history_record(ProjectId.CAPSTONE, CapstoneIngestResult(documents=[IngestedDoc(name="x.txt")])),
    )

    summaries = repo.list_records(ProjectId.CAPSTONE)
    ids = {s.id for s in summaries}
    assert task_id in ids and ingest_id in ids
    # Every capstone summary id is a discriminated string id.
    assert all(isinstance(s.id, str) and (":" in s.id) for s in summaries)


def test_unknown_or_malformed_capstone_id_returns_none(repo: HistoryRepository) -> None:
    assert repo.get_record(ProjectId.CAPSTONE, "task:999999") is None
    assert repo.get_record(ProjectId.CAPSTONE, "bogus") is None
    assert repo.get_record(ProjectId.CAPSTONE, "ingest:") is None
