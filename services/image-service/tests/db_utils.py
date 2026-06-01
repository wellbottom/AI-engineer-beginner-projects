"""Helpers for DB-backed tests against an ephemeral PostgreSQL.

The Image Service's DB-backed property test (Property 35) persists a generated
image to a **real** PostgreSQL and reads its ``BYTEA`` bytes back, so it needs a
reachable database. This module resolves a test database URL from the environment
and probes it with a **short timeout** so a test SKIPS cleanly (never hangs or
hard-fails) when no database is reachable. The orchestrator runs Property 35
against the ephemeral ``postgres`` provided via ``TEST_DATABASE_URL``.

This mirrors ``packages/ai_shared/tests/db_utils.py`` (the agreed skip pattern).

Resolution order for the URL:

1. ``TEST_DATABASE_URL`` (a full SQLAlchemy URL), else
2. the standard ``DB_*`` variables if all are present.

The URL is captured at **import time** (during collection) so it survives any
env isolation a fixture might apply.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from ai_shared.config import Settings

__all__ = [
    "TEST_DB_URL",
    "test_settings",
    "database_reachable",
    "SKIP_REASON",
    "CONNECT_TIMEOUT",
]

#: Short connect timeout (seconds) so an unreachable DB skips instead of hanging.
CONNECT_TIMEOUT = 3


def _resolve_url() -> str | None:
    """Resolve the test database URL from the environment, or ``None``."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if all([host, port, user, password, name]):
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return None


#: The resolved test DB URL, captured at import time (``None`` when unconfigured).
TEST_DB_URL: str | None = _resolve_url()

SKIP_REASON = (
    "No test PostgreSQL configured/reachable: set TEST_DATABASE_URL (or the DB_* "
    "vars) to a reachable ephemeral PostgreSQL to run DB-backed tests."
)


def test_settings() -> Settings:
    """Build a :class:`Settings` whose ``database_url`` is :data:`TEST_DB_URL`."""
    assert TEST_DB_URL is not None, "test_settings() called without a configured URL"
    url = make_url(TEST_DB_URL)
    return Settings(
        llm_base_url="http://localhost:3090/v1",
        llm_api_key="test",
        llm_model="claude-opus-4.7",
        tavily_api_key="test",
        hf_token="test",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        chroma_path="./.chroma",
        db_host=url.host or "localhost",
        db_port=url.port or 5432,
        db_user=url.username or "postgres",
        db_password=url.password or "",
        db_name=url.database or "postgres",
    )


def database_reachable() -> bool:
    """Return ``True`` iff the configured test DB accepts a connection quickly."""
    if TEST_DB_URL is None:
        return False
    try:
        engine = create_engine(
            TEST_DB_URL,
            connect_args={"connect_timeout": CONNECT_TIMEOUT},
            pool_pre_ping=True,
        )
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()
    except (SQLAlchemyError, OSError, Exception):
        return False
