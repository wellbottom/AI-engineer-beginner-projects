"""DB-backed retention + survives-restart + Alembic tests (Task 4.9).

**Validates: Requirements 12.2, 12.3**

Against an ephemeral PostgreSQL:

- **Retention (12.2):** persisting many records never decreases the count and all
  remain retrievable — there is no expiry/cap code path.
- **Survives restart (12.3):** dispose the engine and reconnect a fresh engine to
  the same database; previously persisted records are still returned.
- **Migrations:** ``alembic upgrade head`` runs cleanly on a fresh database and
  creates every history table.

These tests SKIP cleanly when no test database is reachable.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from ai_shared.db import dispose_engine, get_engine, get_sessionmaker
from ai_shared.history import (
    HistoryRepository,
    PlaygroundResult,
    ProjectId,
    build_history_record,
)
from ai_shared.llm_types import Usage
from ai_shared.models import ALL_TABLES, Base

from . import db_utils

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not db_utils.database_reachable(), reason=db_utils.SKIP_REASON
)


def _truncate_all(engine) -> None:
    table_names = ", ".join(t.__tablename__ for t in ALL_TABLES)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


def _make_playground(n: int) -> object:
    return build_history_record(
        ProjectId.PLAYGROUND,
        PlaygroundResult(
            prompt=f"prompt {n}",
            system_prompt=None,
            temperature=1.0,
            max_tokens=128,
            model="claude-opus-4.7",
            response_text=f"answer {n}",
            usage=Usage(prompt_tokens=n, output_tokens=n, total_tokens=2 * n),
        ),
    )


@pytest.fixture()
def fresh_db():
    settings = db_utils.test_settings()
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    _truncate_all(engine)
    yield settings
    _truncate_all(engine)
    dispose_engine(settings)


def test_retention_count_never_decreases_and_all_retrievable(fresh_db):
    settings = fresh_db
    repo = HistoryRepository(get_sessionmaker(settings))

    saved_ids: list[int] = []
    prev_count = 0
    for n in range(1, 31):  # persist many records
        saved_ids.append(repo.save_record(ProjectId.PLAYGROUND, _make_playground(n)))
        count = len(repo.list_records(ProjectId.PLAYGROUND))
        # Count never decreases (no expiry/cap path).
        assert count >= prev_count
        assert count == n
        prev_count = count

    # Every saved record remains retrievable.
    for n, rid in enumerate(saved_ids, start=1):
        rec = repo.get_record(ProjectId.PLAYGROUND, rid)
        assert rec is not None
        assert rec.prompt == f"prompt {n}"


def test_records_survive_engine_dispose_and_reconnect(fresh_db):
    settings = fresh_db

    # Write with the first engine/sessionmaker.
    repo1 = HistoryRepository(get_sessionmaker(settings))
    written = [repo1.save_record(ProjectId.PLAYGROUND, _make_playground(n)) for n in range(1, 6)]

    # Dispose the engine entirely (simulates a service shutdown).
    dispose_engine(settings)

    # Reconnect a brand-new engine/sessionmaker to the same database.
    fresh_settings = db_utils.test_settings()
    repo2 = HistoryRepository(get_sessionmaker(fresh_settings))

    summaries = repo2.list_records(ProjectId.PLAYGROUND)
    assert len(summaries) == len(written)
    for n, rid in enumerate(written, start=1):
        rec = repo2.get_record(ProjectId.PLAYGROUND, rid)
        assert rec is not None
        assert rec.prompt == f"prompt {n}"


def test_alembic_upgrade_head_on_fresh_database():
    """``alembic upgrade head`` creates every history table on a fresh schema.

    Runs the migration into a throwaway PostgreSQL schema so it does not collide
    with the tables the other tests create via ``Base.metadata.create_all``. The
    schema is dropped afterwards.
    """
    settings = db_utils.test_settings()
    engine = get_engine(settings)
    schema = "alembic_test_" + uuid.uuid4().hex[:8]

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        # Point Alembic at the test DB and force every table into the throwaway
        # schema via the connection's search_path (set through the URL options).
        db_url = db_utils.TEST_DB_URL
        # Use -x search_path is not standard; instead set via options query param.
        url_with_schema = (
            f"{db_url}{'&' if '?' in db_url else '?'}options=-csearch_path%3D{schema}"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-x",
                f"db_url={url_with_schema}",
                "upgrade",
                "head",
            ],
            cwd=str(PACKAGE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}"

        # Verify every history table now exists in the throwaway schema.
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema"
                ),
                {"schema": schema},
            ).scalars()
            present = set(rows)
        expected = {t.__tablename__ for t in ALL_TABLES} | {"alembic_version"}
        assert expected.issubset(present), f"missing tables: {expected - present}"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        dispose_engine(settings)
