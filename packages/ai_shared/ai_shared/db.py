"""Shared SQLAlchemy engine/session lifecycle for the History_Store.

Every history-persisting service obtains its engine and ``sessionmaker`` from here
so all six backends connect to the one PostgreSQL Database with an identical
configuration approach (Requirements 3.13, 12.3). The connection URL comes from
:attr:`ai_shared.config.Settings.database_url`
(``postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME``).

Lifecycle (design "Connection lifecycle"):

- :func:`get_engine` builds a pooled :class:`~sqlalchemy.engine.Engine` **once per
  database URL** and caches it, so the connection pool is created at startup and
  reused across requests.
- :func:`get_sessionmaker` returns a cached ``sessionmaker`` bound to that engine.
- :func:`session_scope` is a context manager that opens a short-lived session,
  commits on success, rolls back on error, and always closes — the unit of work
  for a single history write/read.
- :func:`dispose_engine` disposes the pool(s) on FastAPI shutdown.

The engine cache is keyed by the database URL so tests can point at an ephemeral
database without colliding with a previously-built engine. ``pool_pre_ping=True``
guards against stale connections after the database restarts (Requirement 12.3).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings

__all__ = [
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "dispose_engine",
]

# Engine / sessionmaker caches keyed by the database URL. Keying by URL (rather
# than a single module global) lets a service use one engine while tests build a
# distinct engine for an ephemeral database without clobbering each other.
_ENGINES: dict[str, Engine] = {}
_SESSIONMAKERS: dict[str, sessionmaker[Session]] = {}


def get_engine(settings: Settings) -> Engine:
    """Return a cached pooled :class:`Engine` for ``settings.database_url``.

    The engine (and its connection pool) is created once per URL and reused on
    subsequent calls. ``pool_pre_ping=True`` validates a pooled connection before
    use so a database restart does not surface as a stale-connection error.
    """
    url = settings.database_url
    engine = _ENGINES.get(url)
    if engine is None:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        _ENGINES[url] = engine
    return engine


def get_sessionmaker(settings: Settings) -> sessionmaker[Session]:
    """Return a cached ``sessionmaker`` bound to the engine for ``settings``."""
    url = settings.database_url
    maker = _SESSIONMAKERS.get(url)
    if maker is None:
        maker = sessionmaker(bind=get_engine(settings), expire_on_commit=False)
        _SESSIONMAKERS[url] = maker
    return maker


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on clean exit, rolls back on exception, and always closes the session.
    This is the single unit of work used by :class:`ai_shared.history.HistoryRepository`
    for each write/read.
    """
    session = get_sessionmaker(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine(settings: Settings | None = None) -> None:
    """Dispose connection pools on shutdown (FastAPI lifespan).

    With ``settings`` provided, disposes (and forgets) only that database's engine
    and ``sessionmaker``. With no argument, disposes **all** cached engines — handy
    for test teardown.
    """
    if settings is not None:
        url = settings.database_url
        engine = _ENGINES.pop(url, None)
        if engine is not None:
            engine.dispose()
        _SESSIONMAKERS.pop(url, None)
        return

    for engine in _ENGINES.values():
        engine.dispose()
    _ENGINES.clear()
    _SESSIONMAKERS.clear()
