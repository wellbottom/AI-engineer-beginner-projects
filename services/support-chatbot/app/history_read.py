"""Service-layer read helper for a chatbot session's full turn list (BUG-005).

The chatbot history **detail** view (``GET /history/{id}``, Requirements 12.6/13.4)
must show a session's complete, ordered turn list. The shared
:meth:`ai_shared.history.HistoryRepository.get_record` for ``ProjectId.SUPPORT``
intentionally returns only the latest turn's content alongside the session id (its
docstring notes the full list is "available via the relationship for the detail
view"). Rather than change any ``ai_shared`` signature, this small helper reuses the
shared ORM models (:class:`ChatSessionHistory` and its ``turns`` relationship) and
the shared ``sessionmaker`` to read the whole conversation for one session row.

This is logged as **BUG-005** (a tracked follow-up to add a first-class
``ai_shared`` accessor); until then the gap is covered here without expanding the
shared package's public surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from ai_shared.errors import PersistenceError
from ai_shared.models import ChatSessionHistory

__all__ = ["SessionTurn", "SessionDetail", "get_session_detail"]


@dataclass
class SessionTurn:
    """One persisted turn in a session's full detail view."""

    user_message: str
    assistant_reply: str
    created_at: datetime


@dataclass
class SessionDetail:
    """A persisted chat session with its complete, ordered turn list."""

    session_pk: int
    session_id: str
    created_at: datetime
    turns: list[SessionTurn]


def get_session_detail(
    session_factory: sessionmaker[Session],
    session_pk: int,
) -> SessionDetail | None:
    """Return the full ordered turn list for the session row ``session_pk``.

    Reuses the shared ORM ``ChatSessionHistory`` + ``ChatTurnHistory`` relationship
    (ordered by turn id) so the detail endpoint can render the whole conversation.

    Args:
        session_factory: The shared ``sessionmaker`` (from
            :func:`ai_shared.db.get_sessionmaker`).
        session_pk: The session row's surrogate primary key (the id returned by
            ``save_record`` / shown in ``list_records`` summaries).

    Returns:
        A :class:`SessionDetail`, or ``None`` if no session row has that id.

    Raises:
        PersistenceError: On any database failure (mapped to 502 by the endpoint,
            Requirement 13.6).
    """
    session = session_factory()
    try:
        row = session.get(ChatSessionHistory, session_pk)
        if row is None:
            return None
        turns = [
            SessionTurn(
                user_message=t.user_message,
                assistant_reply=t.assistant_reply,
                created_at=t.created_at,
            )
            for t in row.turns  # relationship is ordered by ChatTurnHistory.id
        ]
        return SessionDetail(
            session_pk=int(row.id),
            session_id=row.session_id,
            created_at=row.created_at,
            turns=turns,
        )
    except PersistenceError:
        raise
    except Exception as exc:  # SQLAlchemy / driver failures -> structured error
        raise PersistenceError(
            action="retrieve history",
            reason=str(exc) or None,
            details={"project": "support"},
        ) from exc
    finally:
        session.close()
