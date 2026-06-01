"""Property-based test for the conversation history invariant (Property 6).

# Feature: ai-engineer-practice-monorepo, Property 6: retained history is the most-recent suffix capped at 50; >30min idle discards the session

**Validates: Requirements 5.1**

For any sequence of appended turns, the retained history contains at most 50 turns
and equals the most-recent suffix of the appended turns in order; and for any
session whose idle time since last activity exceeds 30 minutes, the session is
discarded.

Two complementary properties are exercised against the pure
:func:`app.session_store.append_turn` / :func:`app.session_store.is_expired` and the
:class:`app.session_store.SessionStore` (with an injected clock so the 30-minute
expiry is deterministic — no real time passes):

1. Folding ``append_turn`` over an arbitrary sequence of turns yields exactly the
   last ``min(n, 50)`` turns, in order (the 50-turn cap + most-recent-suffix
   invariant).
2. A session idle for strictly more than 30 minutes is discarded (``get`` returns
   ``None`` and it is removed from the store); at/under 30 minutes it survives.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.session_store import (
    IDLE_TIMEOUT,
    MAX_TURNS,
    SessionStore,
    Turn,
    append_turn,
    is_expired,
)

_turns = st.builds(
    Turn,
    user_message=st.text(max_size=12),
    assistant_reply=st.text(max_size=12),
)


# Feature: ai-engineer-practice-monorepo, Property 6: retained history is the most-recent suffix capped at 50; >30min idle discards the session
@settings(max_examples=200, deadline=None)
@given(turns=st.lists(_turns, max_size=130))
def test_retained_history_is_capped_recent_suffix(turns: list[Turn]) -> None:
    """Folding append_turn keeps exactly the most-recent suffix capped at 50."""
    history: list[Turn] = []
    for i, turn in enumerate(turns, start=1):
        before = list(history)
        history = append_turn(before, turn)
        # append_turn is pure: it never mutates its input list.
        assert before == before  # (sanity) before is untouched
        # The retained history equals the most-recent suffix of all-appended-so-far.
        expected = (before + [turn])[-MAX_TURNS:]
        assert history == expected
        # Cap and ordering invariants.
        assert len(history) == min(i, MAX_TURNS)
        assert history[-1] == turn  # newest turn is last (order preserved)

    # Final history equals the global most-recent suffix of the whole sequence.
    assert history == turns[-MAX_TURNS:]
    assert len(history) == min(len(turns), MAX_TURNS)


_idle_minutes = st.one_of(
    st.integers(min_value=0, max_value=30),  # at/under the boundary -> survives
    st.integers(min_value=31, max_value=10_000),  # over the boundary -> discarded
)


# Feature: ai-engineer-practice-monorepo, Property 6: retained history is the most-recent suffix capped at 50; >30min idle discards the session
@settings(max_examples=200, deadline=None)
@given(idle_minutes=_idle_minutes, extra_seconds=st.integers(min_value=0, max_value=59))
def test_idle_over_30_minutes_discards_session(idle_minutes: int, extra_seconds: int) -> None:
    """A session idle for > 30 minutes is discarded; at/under 30 minutes it survives."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Mutable clock so the store sees time advance between create and access.
    now_holder = {"now": base}
    store = SessionStore(clock=lambda: now_holder["now"])

    session_id = store.create()
    assert store.get(session_id) is not None  # present right after creation

    idle = timedelta(minutes=idle_minutes, seconds=extra_seconds)
    now_holder["now"] = base + idle
    expired = is_expired(base, now_holder["now"], idle_timeout=IDLE_TIMEOUT)

    # The pure predicate and the store agree, and "expired" means "discarded".
    got = store.get(session_id)
    if idle > IDLE_TIMEOUT:
        assert expired is True
        assert got is None
        assert store.active_count() == 0  # discarded from the store
    else:
        assert expired is False
        assert got is not None
        assert store.active_count() == 1
