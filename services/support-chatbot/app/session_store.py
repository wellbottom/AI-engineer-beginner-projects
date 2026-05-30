"""In-memory active chat session store + pure history helpers (Requirement 5.1).

The Support Chatbot keeps each active conversation in memory as a :class:`Session`
(an ordered list of completed :class:`Turn` objects plus a last-activity
timestamp). Two invariants govern the in-memory state (Requirement 5.1, Property 6):

1. **50-turn cap.** A session retains at most the 50 most-recent turns. The pure
   function :func:`append_turn` implements this — given the current history and a
   new turn it returns the most-recent suffix of length <= 50, in order. Being
   pure (no mutation, no I/O) it is directly property-testable (Property 6).
2. **30-minute idle expiry.** A session that has been idle (no activity) for more
   than 30 minutes is discarded. :func:`is_expired` is the pure predicate; the
   :class:`SessionStore` enforces it lazily on access (an expired session is
   dropped and treated as absent) and via an explicit :meth:`SessionStore.sweep`.

This in-memory cap/expiry is **independent of durable persistence** (Requirement
12.6): discarding or trimming the in-memory session never touches the History_Store
rows written per completed turn. The store's clock is injectable so the 30-minute
expiry is deterministically testable without real time passing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

__all__ = [
    "Turn",
    "Session",
    "SessionStore",
    "append_turn",
    "is_expired",
    "MAX_TURNS",
    "IDLE_TIMEOUT",
]

#: Maximum number of turns retained in an in-memory active session (Requirement 5.1).
MAX_TURNS = 50

#: Idle duration after which an in-memory session is discarded (Requirement 5.1).
IDLE_TIMEOUT = timedelta(minutes=30)


@dataclass(frozen=True)
class Turn:
    """One completed conversation turn: a user message and the assistant reply.

    Frozen so a retained history is an immutable sequence — :func:`append_turn`
    returns a new list rather than mutating an existing one.
    """

    user_message: str
    assistant_reply: str


@dataclass
class Session:
    """An in-memory active chat session (Requirement 5.1).

    Attributes:
        session_id: The opaque session identifier shared with the frontend.
        turns: The retained, ordered list of completed turns (at most
            :data:`MAX_TURNS`).
        last_activity: Timestamp of the most recent activity; drives the
            30-minute idle expiry.
    """

    session_id: str
    turns: list[Turn] = field(default_factory=list)
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def append_turn(history: list[Turn], turn: Turn) -> list[Turn]:
    """Append ``turn`` to ``history`` keeping at most the 50 most-recent turns.

    Pure function (Property 6): returns a **new** list equal to the most-recent
    suffix of ``history + [turn]`` capped at :data:`MAX_TURNS`, preserving order.
    The input list is never mutated.

    Args:
        history: The current retained history (oldest-first).
        turn: The new completed turn to append.

    Returns:
        The new retained history (oldest-first), length ``min(len(history)+1, 50)``.
    """
    appended = list(history)
    appended.append(turn)
    if len(appended) > MAX_TURNS:
        # Keep only the most-recent suffix of length MAX_TURNS, in order.
        return appended[-MAX_TURNS:]
    return appended


def is_expired(
    last_activity: datetime,
    now: datetime,
    *,
    idle_timeout: timedelta = IDLE_TIMEOUT,
) -> bool:
    """Return ``True`` iff the idle time since ``last_activity`` exceeds the timeout.

    Pure predicate (Property 6): a session whose idle time (``now - last_activity``)
    is strictly greater than ``idle_timeout`` (30 minutes) is expired. Exactly at
    the boundary (idle == 30 minutes) the session is *not* yet expired.
    """
    return (now - last_activity) > idle_timeout


def _utcnow() -> datetime:
    """Timezone-aware current time (UTC); the store's default clock."""
    return datetime.now(timezone.utc)


class SessionStore:
    """Thread-unaware in-memory map of ``session_id -> Session`` (Requirement 5.1).

    Enforces the 50-turn cap (via :func:`append_turn`) and the 30-minute idle
    expiry (via :func:`is_expired`, checked lazily on access and on
    :meth:`sweep`). The ``clock`` is injectable so expiry is deterministically
    testable.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    # -- lifecycle --------------------------------------------------------- #
    def create(self) -> str:
        """Create a new empty session and return its generated id."""
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = Session(
            session_id=session_id,
            turns=[],
            last_activity=self._clock(),
        )
        return session_id

    def get(self, session_id: str) -> Session | None:
        """Return the active session, or ``None`` if absent or expired.

        Lazily enforces the 30-minute idle expiry: an expired session is discarded
        and treated as absent (Requirement 5.1). Reading a session does **not**
        refresh its activity timestamp — only appending a turn (genuine activity)
        does, so an idle session still expires on schedule.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if is_expired(session.last_activity, self._clock()):
            # Discard the expired in-memory session; the durable History_Records
            # are untouched (Requirement 12.6).
            del self._sessions[session_id]
            return None
        return session

    def get_or_create(self, session_id: str) -> Session:
        """Return the active session for ``session_id``, creating it if absent/expired.

        ``POST /chat`` accepts a client-supplied ``session_id``; if it is unknown
        (never created, or already expired and discarded) a fresh empty session is
        created under that id so the conversation can proceed.
        """
        session = self.get(session_id)
        if session is not None:
            return session
        session = Session(
            session_id=session_id,
            turns=[],
            last_activity=self._clock(),
        )
        self._sessions[session_id] = session
        return session

    def append(self, session_id: str, turn: Turn) -> Session:
        """Append a completed ``turn`` to the session, applying the 50-turn cap.

        Updates the session's ``last_activity`` to "now" (genuine activity) and
        replaces its turns with ``append_turn(history, turn)``. Creates the session
        if it does not currently exist. Returns the updated session.
        """
        current = self.get_or_create(session_id)
        updated = replace(
            current,
            turns=append_turn(current.turns, turn),
            last_activity=self._clock(),
        )
        self._sessions[session_id] = updated
        return updated

    def delete(self, session_id: str) -> bool:
        """Discard a session immediately; return ``True`` if one was present.

        Backs ``DELETE /session/{id}``. The durable History_Records are unaffected
        (Requirement 12.6).
        """
        return self._sessions.pop(session_id, None) is not None

    def sweep(self) -> int:
        """Discard every expired session; return the number removed.

        Provides an eager alternative to the lazy on-access expiry check (a
        background sweep could call this periodically).
        """
        now = self._clock()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if is_expired(session.last_activity, now)
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    # -- introspection (tests / health) ----------------------------------- #
    def active_count(self) -> int:
        """Number of sessions currently held in memory (without sweeping)."""
        return len(self._sessions)
