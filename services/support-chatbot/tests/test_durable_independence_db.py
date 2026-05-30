"""DB-backed property test: durable history is independent of the in-memory
session lifecycle (Property 36).

# Feature: ai-engineer-practice-monorepo, Property 36: discarding/expiring the in-memory session leaves all persisted records unchanged and retrievable

**Validates: Requirements 5.1, 12.6**

For any sequence of persisted chatbot turns, discarding or expiring the in-memory
active session (after 30 minutes of inactivity or beyond the 50-turn cap) leaves
every previously persisted History_Record unchanged and still retrievable, so the
durable record's availability does not depend on the in-memory session staying
alive.

Each Hypothesis example, against a **real ephemeral PostgreSQL**:

1. Truncates the chat tables (so examples are independent), then persists ``N``
   turns under one ``session_id`` via the real :class:`HistoryRepository`
   (``persist_record``) while also appending them to the in-memory
   :class:`SessionStore` — exactly what ``chat_sse`` does on each completed turn.
2. Snapshots the durable state (the full ordered turn list + the session summary).
3. Discards the in-memory session two ways across the input space — a >30-minute
   idle expiry (clock advanced) and an explicit delete; for ``N > 50`` the
   in-memory session is also trimmed to the 50-turn cap while the DB keeps all
   ``N`` turns.
4. Re-reads the durable state and asserts it is byte-for-byte unchanged and still
   retrievable, even though the in-memory session is gone/trimmed.

The test SKIPS cleanly when no PostgreSQL is reachable (see ``db_utils``), so it
never hangs or hard-fails without a database; the orchestrator runs it against an
ephemeral ``postgres:16``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from ai_shared.db import dispose_engine, get_engine, get_sessionmaker
from ai_shared.history import (
    ChatTurnResult,
    HistoryRepository,
    ProjectId,
    _strip_nul,
    build_history_record,
)
from ai_shared.models import ChatSessionHistory, ChatTurnHistory, Base
from ai_shared.persistence import persist_record

from app.history_read import get_session_detail
from app.session_store import MAX_TURNS, SessionStore, Turn

from . import db_utils

pytestmark = pytest.mark.skipif(
    not db_utils.database_reachable(), reason=db_utils.SKIP_REASON
)

# Chat tables only — truncated between examples to keep DB state independent.
_CHAT_TABLES = "chat_turn_history, chat_session_history"


@pytest.fixture(scope="module")
def db():
    """Module-scoped engine + sessionmaker against the ephemeral DB.

    Creates the schema once; each example truncates the chat tables itself.
    """
    settings_obj = db_utils.test_settings()
    engine = get_engine(settings_obj)
    Base.metadata.create_all(engine)
    session_factory = get_sessionmaker(settings_obj)
    yield engine, session_factory
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_CHAT_TABLES} RESTART IDENTITY CASCADE"))
    dispose_engine(settings_obj)


_turn_pairs = st.lists(
    st.tuples(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=20)),
    min_size=1,
    max_size=55,  # spans past the 50-turn in-memory cap
)


# Feature: ai-engineer-practice-monorepo, Property 36: discarding/expiring the in-memory session leaves all persisted records unchanged and retrievable
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pairs=_turn_pairs, discard_mode=st.sampled_from(["idle", "delete"]))
def test_discarding_session_leaves_persisted_records_unchanged(db, pairs, discard_mode):
    engine, session_factory = db

    # (1) Clean slate for this example.
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_CHAT_TABLES} RESTART IDENTITY CASCADE"))

    repository = HistoryRepository(session_factory)
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = {"now": base}
    store = SessionStore(clock=lambda: clock["now"])

    session_id = "sess-durable"
    store.get_or_create(session_id)

    # (1) Persist N turns + mirror them into the in-memory session.
    saved_id = None
    for user_msg, reply in pairs:
        store.append(session_id, Turn(user_message=user_msg, assistant_reply=reply))
        record = build_history_record(
            ProjectId.SUPPORT,
            ChatTurnResult(session_id=session_id, user_message=user_msg, assistant_reply=reply),
        )
        outcome = persist_record(repository, ProjectId.SUPPORT, record)
        assert outcome.ok is True
        saved_id = outcome.saved_id

    # In-memory session holds at most the 50-turn cap, even though DB keeps all N.
    in_memory = store.get(session_id)
    assert in_memory is not None
    assert len(in_memory.turns) == min(len(pairs), MAX_TURNS)

    # (2) Snapshot the durable state before discarding the in-memory session.
    # Persisted TEXT is NUL-sanitized at record construction (BUG-006), so the
    # expected persisted content is the sanitized form of each pair. Non-NUL text
    # (the common case) is unchanged, so this still asserts exact content + order.
    expected_pairs = [(_strip_nul(u), _strip_nul(a)) for u, a in pairs]
    detail_before = get_session_detail(session_factory, saved_id)
    assert detail_before is not None
    assert detail_before.session_id == session_id
    assert len(detail_before.turns) == len(pairs)  # ALL turns persisted (no cap)
    persisted_before = [(t.user_message, t.assistant_reply) for t in detail_before.turns]
    assert persisted_before == expected_pairs  # exact sanitized content + order
    summaries_before = repository.list_records(ProjectId.SUPPORT)
    assert len(summaries_before) == 1

    # (3) Discard / expire the in-memory session.
    if discard_mode == "idle":
        clock["now"] = base + timedelta(minutes=30, seconds=1)  # > 30 min idle
        assert store.get(session_id) is None  # lazily discarded
    else:
        assert store.delete(session_id) is True
    assert store.active_count() == 0  # in-memory session is gone

    # (4) The durable records are unchanged and still retrievable.
    detail_after = get_session_detail(session_factory, saved_id)
    assert detail_after is not None
    assert detail_after.session_id == session_id
    assert detail_after.session_pk == detail_before.session_pk
    persisted_after = [(t.user_message, t.assistant_reply) for t in detail_after.turns]
    assert persisted_after == persisted_before  # unchanged
    assert len(persisted_after) == len(pairs)

    summaries_after = repository.list_records(ProjectId.SUPPORT)
    assert len(summaries_after) == 1
    assert summaries_after[0].id == summaries_before[0].id
    assert summaries_after[0].label == session_id


def test_models_import_is_used():
    """Guard: ChatTurnHistory/ChatSessionHistory are the relational tables used."""
    assert ChatSessionHistory.__tablename__ == "chat_session_history"
    assert ChatTurnHistory.__tablename__ == "chat_turn_history"
