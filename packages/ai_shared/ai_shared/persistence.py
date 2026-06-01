"""Best-effort persistence wrapper implementing the Requirement 12.4 policy.

Persisting a History_Record must **never** fail the user-facing operation. This
module wraps :meth:`ai_shared.history.HistoryRepository.save_record` so a service
can persist a record and obtain a structured :class:`PersistenceOutcome` that:

- on success carries ``persistence = {"ok": True}`` (and the saved row id);
- on :class:`~ai_shared.errors.PersistenceError` still leaves the operation result
  intact, generates a correlation ``operation_id`` (a UUID4), **logs** the failure
  with that id, and carries ``persistence = {"ok": False, "operation_id": ...}``.

A successful operation is *never* converted into an error. The outcome exposes two
attachers so callers can fold the persistence indication onto either response
shape (design "History-write-failure policy"):

- :meth:`PersistenceOutcome.attach_to_body` — merges ``persistence`` into a
  non-streamed JSON body (image ``POST /generate``, capstone ``POST /documents``).
- :meth:`PersistenceOutcome.attach_to_done` — merges ``persistence`` onto a
  streamed endpoint's terminal ``done`` event payload, so the SSE contract stays
  intact (``done`` remains the single terminal success event; a persistence
  failure does not emit an ``error`` event).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .errors import PersistenceError
from .history import HistoryRecord, HistoryRepository, ProjectId, SavedId

__all__ = [
    "PersistenceOutcome",
    "persist_record",
]

logger = logging.getLogger("ai_shared.persistence")


@dataclass
class PersistenceOutcome:
    """The result of a best-effort persistence attempt (Requirement 12.4).

    Attributes:
        ok: ``True`` when the write succeeded, ``False`` when it failed.
        saved_id: The new row id on success, else ``None``.
        operation_id: The correlation id generated on failure (``None`` on success).
    """

    ok: bool
    saved_id: SavedId | None = None
    operation_id: str | None = None

    @property
    def indication(self) -> dict[str, Any]:
        """The ``persistence`` indication object for the response.

        ``{"ok": True}`` on success; ``{"ok": False, "operation_id": ...}`` on
        failure. The ``operation_id`` is included only on failure so it matches the
        logged correlation id.
        """
        if self.ok:
            return {"ok": True}
        return {"ok": False, "operation_id": self.operation_id}

    def attach_to_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return ``body`` with the ``persistence`` indication merged in.

        Used by non-streamed endpoints whose result is a JSON object. The original
        operation result keys are left untouched (the result is never altered).
        """
        merged = dict(body)
        merged["persistence"] = self.indication
        return merged

    def attach_to_done(self, done_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a terminal ``done`` event payload carrying the indication.

        Used by streamed (SSE) endpoints: the result has already been streamed as
        ``data``/``progress`` events, so the indication rides on ``done``. Any
        existing ``done`` metadata (e.g. token ``usage``) is preserved.
        """
        merged = dict(done_data) if done_data else {}
        merged["persistence"] = self.indication
        return merged


def persist_record(
    repository: HistoryRepository,
    project: ProjectId,
    record: HistoryRecord,
    *,
    operation_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    log: logging.Logger | None = None,
) -> PersistenceOutcome:
    """Persist ``record`` best-effort and return a :class:`PersistenceOutcome`.

    Never raises for a :class:`PersistenceError`: on failure it generates an
    ``operation_id``, logs the failure with that id, and returns
    ``PersistenceOutcome(ok=False, operation_id=...)``. On success it returns
    ``PersistenceOutcome(ok=True, saved_id=...)``.

    Args:
        repository: The shared :class:`HistoryRepository`.
        project: Which mini-project's table to write.
        record: The constructed :class:`HistoryRecord` to persist.
        operation_id_factory: Generates the correlation id on failure (overridable
            for deterministic tests). Defaults to a UUID4 string.
        log: Logger to use (defaults to the module logger).

    Returns:
        A :class:`PersistenceOutcome`. The caller attaches ``outcome.indication``
        (or uses :meth:`PersistenceOutcome.attach_to_body` /
        :meth:`PersistenceOutcome.attach_to_done`) to its response.
    """
    active_log = log if log is not None else logger
    try:
        saved_id = repository.save_record(project, record)
        return PersistenceOutcome(ok=True, saved_id=saved_id)
    except PersistenceError as exc:
        operation_id = operation_id_factory()
        active_log.error(
            "History persistence failed (operation_id=%s, project=%s): %s",
            operation_id,
            project.value,
            exc.reason,
        )
        return PersistenceOutcome(ok=False, operation_id=operation_id)
