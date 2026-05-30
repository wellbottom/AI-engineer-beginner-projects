"""Shared History_Store repository and pure record construction (Requirement 12).

This module is the single write/read path every backend uses for durable history:

- :class:`ProjectId` — an enum over the six mini-projects (string values match the
  frontend ``ProjectId`` union).
- The **input result types** a service hands to :func:`build_history_record`
  (``PlaygroundResult``, ``ChatTurnResult``, ``WebAgentResult``,
  ``DeepResearchResult``, ``ImageGenerationResult``, ``CapstoneTaskResult``,
  ``CapstoneIngestResult``) plus the small structured sub-objects they carry
  (:class:`Citation`, :class:`SubQuestion`, :class:`ReportSection`,
  :class:`ResearchReport`, :class:`ToolInvocation`, :class:`IngestedDoc`).
- The :data:`HistoryRecord` **tagged union** (one variant dataclass per persisted
  table shape) plus :class:`HistorySummary` for list views.
- :func:`build_history_record` — a **pure** mapping from a service result onto its
  ``HistoryRecord`` variant with a creation timestamp (Property 33). It needs no
  database connection, so it is directly property-testable.
- :class:`HistoryRepository` — ``save_record`` / ``list_records`` / ``get_record``
  backed by the shared SQLAlchemy ``sessionmaker`` (Requirements 12.1, 13.3).

Structured sub-objects are normalized to plain JSON-able structures (``dict`` /
``list``) by :func:`build_history_record` so they map straight onto the ``JSONB``
columns in :mod:`ai_shared.models` and round-trip exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Union

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .errors import PersistenceError
from .llm_types import Usage
from .models import (
    Base,
    CapstoneIngestHistory,
    CapstoneTaskHistory,
    ChatSessionHistory,
    ChatTurnHistory,
    DeepResearchHistory,
    ImageHistory,
    PlaygroundHistory,
    WebAgentHistory,
)

__all__ = [
    "ProjectId",
    "SavedId",
    # structured sub-objects
    "Citation",
    "SubQuestion",
    "ReportSection",
    "ResearchReport",
    "ToolInvocation",
    "IngestedDoc",
    # input result types
    "PlaygroundResult",
    "ChatTurnResult",
    "WebAgentResult",
    "DeepResearchResult",
    "ImageGenerationResult",
    "CapstoneTaskResult",
    "CapstoneIngestResult",
    # persisted record variants
    "PlaygroundRecord",
    "ChatTurnRecord",
    "WebAgentRecord",
    "DeepResearchRecord",
    "ImageRecord",
    "CapstoneTaskRecord",
    "CapstoneIngestRecord",
    "HistoryRecord",
    "HistorySummary",
    # construction + repository
    "build_history_record",
    "HistoryRepository",
]

#: A persisted record's identifier.
#:
#: For five of the six projects this is the plain integer surrogate primary key.
#: The **capstone** project persists into two independently-sequenced tables
#: (``capstone_task_history`` and ``capstone_ingest_history``), so a task row and
#: an ingest row can share the same numeric id. To keep a per-id detail lookup
#: unambiguous (BUG-003), capstone ids are ``kind``-discriminated **strings** of the
#: form ``"task:<n>"`` / ``"ingest:<n>"``. Hence the union of ``int`` and ``str``.
SavedId = Union[int, str]

#: Max length of the short label shown in history-list summaries.
_LABEL_MAX = 80

#: Valid capstone id discriminators -> their ORM table class.
_CAPSTONE_KIND_TABLE: dict[str, type] = {
    "task": CapstoneTaskHistory,
    "ingest": CapstoneIngestHistory,
}


class ProjectId(str, Enum):
    """The six mini-projects (string values mirror the frontend ``ProjectId``)."""

    PLAYGROUND = "playground"
    SUPPORT = "support"
    WEB_AGENT = "web-agent"
    DEEP_RESEARCH = "deep-research"
    IMAGE = "image"
    CAPSTONE = "capstone"


# --------------------------------------------------------------------------- #
# Structured sub-objects (mirror the design Data Models; small + JSON-able).
# --------------------------------------------------------------------------- #
@dataclass
class Citation:
    """A source reference accompanying an answer or report section."""

    url: str
    title: str = ""

    def to_json(self) -> dict:
        return {"url": self.url, "title": self.title}


@dataclass
class SubQuestion:
    """A Deep Research sub-question."""

    id: int
    text: str

    def to_json(self) -> dict:
        return {"id": self.id, "text": self.text}


@dataclass
class ReportSection:
    """One section of a Deep Research report (one per sub-question)."""

    sub_question: str
    body: str
    citations: list[Citation] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "sub_question": self.sub_question,
            "body": self.body,
            "citations": [c.to_json() for c in self.citations],
        }


@dataclass
class ResearchReport:
    """A full Deep Research report: title, intro, sections, conclusion."""

    title: str
    introduction: str
    sections: list[ReportSection]
    conclusion: str

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "introduction": self.introduction,
            "sections": [s.to_json() for s in self.sections],
            "conclusion": self.conclusion,
        }


@dataclass
class ToolInvocation:
    """A Capstone MCP tool invocation with its success/failure outcome."""

    tool: str
    ok: bool
    error: str | None = None

    def to_json(self) -> dict:
        return {"tool": self.tool, "ok": self.ok, "error": self.error}


@dataclass
class IngestedDoc:
    """A document successfully ingested by the Capstone service."""

    name: str
    chunks: int = 0


# --------------------------------------------------------------------------- #
# Input result types (what a service passes to ``build_history_record``).
# --------------------------------------------------------------------------- #
@dataclass
class PlaygroundResult:
    """Completed LLM Playground run (Requirement 12.5)."""

    prompt: str
    system_prompt: str | None
    temperature: float
    max_tokens: int
    model: str
    response_text: str
    usage: Usage


@dataclass
class ChatTurnResult:
    """A completed Support Chatbot conversation turn (Requirement 12.6)."""

    session_id: str
    user_message: str
    assistant_reply: str


@dataclass
class WebAgentResult:
    """A completed Ask-the-Web answer (Requirement 12.7)."""

    question: str
    answer: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class DeepResearchResult:
    """A completed Deep Research report (Requirement 12.8)."""

    topic: str
    sub_questions: list[SubQuestion]
    report: ResearchReport
    citations: list[Citation] = field(default_factory=list)


@dataclass
class ImageGenerationResult:
    """A generated image (Requirement 12.9)."""

    prompt: str
    model: str
    image_bytes: bytes
    mime_type: str


@dataclass
class CapstoneTaskResult:
    """A completed Capstone task run (Requirement 12.10)."""

    task_text: str
    final_answer: str
    tools_invoked: list[ToolInvocation]
    sources: list[str]
    step_limit_reached: bool


@dataclass
class CapstoneIngestResult:
    """A completed Capstone document ingestion (Requirement 12.11)."""

    documents: list[IngestedDoc]


# --------------------------------------------------------------------------- #
# Persisted record variants (the tagged union; created_at, no surrogate id).
# --------------------------------------------------------------------------- #
@dataclass
class PlaygroundRecord:
    prompt: str
    system_prompt: str | None
    temperature: float
    max_tokens: int
    model: str
    response_text: str
    usage: dict
    created_at: datetime


@dataclass
class ChatTurnRecord:
    session_id: str
    user_message: str
    assistant_reply: str
    created_at: datetime


@dataclass
class WebAgentRecord:
    question: str
    answer: str
    citations: list[dict]
    created_at: datetime


@dataclass
class DeepResearchRecord:
    topic: str
    sub_questions: list[dict]
    report: dict
    citations: list[dict]
    created_at: datetime


@dataclass
class ImageRecord:
    prompt: str
    model: str
    image_bytes: bytes
    mime_type: str
    created_at: datetime


@dataclass
class CapstoneTaskRecord:
    task_text: str
    final_answer: str
    tools_invoked: list[dict]
    sources: list[str]
    step_limit_reached: bool
    created_at: datetime


@dataclass
class CapstoneIngestRecord:
    documents: list[str]
    created_at: datetime


#: The tagged union of persisted record shapes (one variant per table shape).
HistoryRecord = Union[
    PlaygroundRecord,
    ChatTurnRecord,
    WebAgentRecord,
    DeepResearchRecord,
    ImageRecord,
    CapstoneTaskRecord,
    CapstoneIngestRecord,
]


@dataclass
class HistorySummary:
    """A newest-first list entry: surrogate id, creation timestamp, short label."""

    id: SavedId
    created_at: datetime
    label: str


def _now() -> datetime:
    """Timezone-aware creation timestamp (UTC)."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# NUL-byte sanitization (BUG-006).
#
# PostgreSQL ``text``/``varchar`` columns cannot store the NUL byte (``\x00``);
# attempting to persist one raises ``psycopg.DataError`` ("PostgreSQL text fields
# cannot contain NUL (0x00) bytes"). User-supplied text reaches durable history in
# every service (playground prompts/responses, chatbot messages, web-agent
# questions/answers + citation titles, deep-research topics/report bodies, capstone
# task text/tool errors/document names, ...), so the failure is cross-cutting, not
# chatbot-specific. Sanitizing NUL out at record construction keeps durable history
# intact ("keep everything", Requirement 12.2) instead of silently dropping records
# via the best-effort write wrapper (Requirement 12.4), and it is applied once here
# for all six projects. BYTEA columns (``ImageRecord.image_bytes``) legitimately
# hold ``0x00`` and are deliberately left untouched.
# --------------------------------------------------------------------------- #
def _strip_nul(s: str) -> str:
    """Remove NUL bytes (``\\x00``) from a string; a no-op for normal text.

    Postgres text columns reject ``\\x00`` (BUG-006). Stripping it lets the record
    persist instead of being dropped. Normal text (no NUL) is returned unchanged,
    so non-NUL input round-trips byte-for-byte.
    """
    return s.replace("\x00", "") if "\x00" in s else s


def _strip_nul_opt(s: str | None) -> str | None:
    """:func:`_strip_nul` that passes ``None`` through unchanged (optional fields)."""
    return None if s is None else _strip_nul(s)


def _sanitize_json(value):
    """Recursively strip NUL bytes from strings inside a JSON-able structure.

    Walks ``dict``/``list`` containers and sanitizes every contained ``str`` (keys
    and values), leaving non-string scalars (``int``/``float``/``bool``/``None``)
    untouched. Used for the normalized JSONB payloads (citations, report bodies,
    sub-questions, tool invocations, ...) so no nested text carries a ``\\x00`` into
    a JSONB ``text`` field.
    """
    if isinstance(value, str):
        return _strip_nul(value)
    if isinstance(value, dict):
        return {_strip_nul(k) if isinstance(k, str) else k: _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(v) for v in value]
    return value


def build_history_record(
    project: ProjectId,
    result: object,
    *,
    created_at: datetime | None = None,
) -> HistoryRecord:
    """Map a service's completed-operation ``result`` onto its ``HistoryRecord``.

    This is a **pure** function (Property 33): it performs no I/O and needs no
    database connection. The structured sub-objects are normalized to plain
    JSON-able structures so they map straight onto the ``JSONB`` columns. A
    creation timestamp is always attached (Requirement 12.1).

    For :data:`ProjectId.CAPSTONE` the concrete ``result`` type disambiguates the
    two capstone record kinds (task run vs document ingestion).

    Raises:
        TypeError: If ``result`` is not the expected type for ``project``.
    """
    ts = created_at if created_at is not None else _now()

    # Every persisted TEXT field is run through ``_strip_nul`` (and nested JSON-able
    # structures through ``_sanitize_json``) so a stray ``\x00`` never reaches a
    # Postgres text/varchar column and drops the record (BUG-006). Image BYTEA is
    # left untouched. Non-NUL text is returned unchanged, so it round-trips exactly.
    if project is ProjectId.PLAYGROUND:
        r = _expect(result, PlaygroundResult, project)
        return PlaygroundRecord(
            prompt=_strip_nul(r.prompt),
            system_prompt=_strip_nul_opt(r.system_prompt),
            temperature=r.temperature,
            max_tokens=r.max_tokens,
            model=_strip_nul(r.model),
            response_text=_strip_nul(r.response_text),
            usage=r.usage.to_dict(),
            created_at=ts,
        )

    if project is ProjectId.SUPPORT:
        r = _expect(result, ChatTurnResult, project)
        return ChatTurnRecord(
            session_id=_strip_nul(r.session_id),
            user_message=_strip_nul(r.user_message),
            assistant_reply=_strip_nul(r.assistant_reply),
            created_at=ts,
        )

    if project is ProjectId.WEB_AGENT:
        r = _expect(result, WebAgentResult, project)
        return WebAgentRecord(
            question=_strip_nul(r.question),
            answer=_strip_nul(r.answer),
            citations=[_sanitize_json(c.to_json()) for c in r.citations],
            created_at=ts,
        )

    if project is ProjectId.DEEP_RESEARCH:
        r = _expect(result, DeepResearchResult, project)
        return DeepResearchRecord(
            topic=_strip_nul(r.topic),
            sub_questions=[_sanitize_json(sq.to_json()) for sq in r.sub_questions],
            report=_sanitize_json(r.report.to_json()),
            citations=[_sanitize_json(c.to_json()) for c in r.citations],
            created_at=ts,
        )

    if project is ProjectId.IMAGE:
        r = _expect(result, ImageGenerationResult, project)
        return ImageRecord(
            prompt=_strip_nul(r.prompt),
            model=_strip_nul(r.model),
            image_bytes=r.image_bytes,  # BYTEA: 0x00 is legitimate, never sanitized.
            mime_type=_strip_nul(r.mime_type),
            created_at=ts,
        )

    if project is ProjectId.CAPSTONE:
        if isinstance(result, CapstoneIngestResult):
            return CapstoneIngestRecord(
                documents=[_strip_nul(d.name) for d in result.documents],
                created_at=ts,
            )
        if isinstance(result, CapstoneTaskResult):
            return CapstoneTaskRecord(
                task_text=_strip_nul(result.task_text),
                final_answer=_strip_nul(result.final_answer),
                tools_invoked=[_sanitize_json(t.to_json()) for t in result.tools_invoked],
                sources=[_strip_nul(s) for s in result.sources],
                step_limit_reached=result.step_limit_reached,
                created_at=ts,
            )
        raise TypeError(
            "capstone result must be CapstoneTaskResult or CapstoneIngestResult, "
            f"got {type(result).__name__}"
        )

    raise TypeError(f"Unknown project: {project!r}")  # pragma: no cover - exhaustive


def _expect(result: object, expected: type, project: ProjectId):
    """Validate ``result`` is ``expected`` for ``project``; return it for chaining."""
    if not isinstance(result, expected):
        raise TypeError(
            f"{project.value} expects a {expected.__name__}, "
            f"got {type(result).__name__}"
        )
    return result


def _truncate(text: str) -> str:
    """Trim a label to :data:`_LABEL_MAX` characters with an ellipsis."""
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "\u2026"


def _capstone_id(kind: str, numeric_id: int) -> str:
    """Build a ``kind``-discriminated capstone id, e.g. ``"task:12"`` (BUG-003)."""
    return f"{kind}:{int(numeric_id)}"


def _parse_capstone_id(record_id: SavedId) -> tuple[type, int] | None:
    """Parse a discriminated capstone id into ``(ORM class, numeric id)``.

    Accepts ids of the form ``"task:<n>"`` / ``"ingest:<n>"`` (the form produced by
    :meth:`HistoryRepository.save_record` / ``list_records`` for capstone). Returns
    ``None`` for any unknown discriminator or malformed id (e.g. a bare int, a
    missing/blank numeric part, or a non-integer numeric part) so callers can map
    it to a ``None`` (not-found) detail lookup.
    """
    if not isinstance(record_id, str):
        return None
    prefix, sep, rest = record_id.partition(":")
    if not sep:
        return None
    orm_class = _CAPSTONE_KIND_TABLE.get(prefix)
    if orm_class is None:
        return None
    try:
        numeric_id = int(rest)
    except ValueError:
        return None
    return orm_class, numeric_id


class HistoryRepository:
    """Persists and retrieves History_Records for all six mini-projects.

    Backed by the shared :class:`sqlalchemy.orm.sessionmaker` from
    :func:`ai_shared.db.get_sessionmaker`. Each method runs in its own short-lived
    session/transaction.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- write ------------------------------------------------------------- #
    def save_record(self, project: ProjectId, record: HistoryRecord) -> SavedId:
        """Persist ``record`` in a single transaction; return its new row id.

        For the chatbot the session row is found-or-created by ``session_id`` and
        the turn is appended under it (still one transaction); the returned id is
        the **session** row id (an ``int``), which backs the per-session history
        detail view.

        For the **capstone** project the returned id is a ``kind``-discriminated
        string — ``"task:<n>"`` for a :class:`CapstoneTaskRecord` and
        ``"ingest:<n>"`` for a :class:`CapstoneIngestRecord` — because its two
        tables have independent id sequences (BUG-003). Every other project returns
        the plain integer surrogate id.

        Raises:
            PersistenceError: On any database failure. Callers apply the
                Requirement 12.4 policy (return the result, log + flag persistence).
        """
        try:
            with self._begin() as session:
                if isinstance(record, ChatTurnRecord):
                    return self._save_chat_turn(session, record)
                orm_obj = self._record_to_orm(record)
                session.add(orm_obj)
                session.flush()  # populate the autoincrement id before commit
                numeric_id = int(orm_obj.id)
                # Capstone persists into two independently-sequenced tables, so its
                # id is kind-discriminated ("task:<n>"/"ingest:<n>") to stay
                # unambiguous for per-id detail lookups (BUG-003).
                if isinstance(record, CapstoneTaskRecord):
                    return _capstone_id("task", numeric_id)
                if isinstance(record, CapstoneIngestRecord):
                    return _capstone_id("ingest", numeric_id)
                return numeric_id
        except SQLAlchemyError as exc:
            raise PersistenceError(
                action="history persistence",
                reason=str(exc) or None,
                details={"project": project.value},
            ) from exc

    def _save_chat_turn(self, session: Session, record: ChatTurnRecord) -> SavedId:
        """Find-or-create the session row, append the turn; return the session id."""
        existing = session.execute(
            select(ChatSessionHistory)
            .where(ChatSessionHistory.session_id == record.session_id)
            .order_by(ChatSessionHistory.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        if existing is None:
            existing = ChatSessionHistory(
                session_id=record.session_id,
                created_at=record.created_at,
            )
            session.add(existing)
            session.flush()

        session.add(
            ChatTurnHistory(
                session_pk=existing.id,
                user_message=record.user_message,
                assistant_reply=record.assistant_reply,
                created_at=record.created_at,
            )
        )
        session.flush()
        return int(existing.id)

    @staticmethod
    def _record_to_orm(record: HistoryRecord) -> Base:
        """Map a (non-chatbot) record variant onto its ORM row."""
        if isinstance(record, PlaygroundRecord):
            return PlaygroundHistory(
                prompt=record.prompt,
                system_prompt=record.system_prompt,
                temperature=record.temperature,
                max_tokens=record.max_tokens,
                model=record.model,
                response_text=record.response_text,
                usage=record.usage,
                created_at=record.created_at,
            )
        if isinstance(record, WebAgentRecord):
            return WebAgentHistory(
                question=record.question,
                answer=record.answer,
                citations=record.citations,
                created_at=record.created_at,
            )
        if isinstance(record, DeepResearchRecord):
            return DeepResearchHistory(
                topic=record.topic,
                sub_questions=record.sub_questions,
                report=record.report,
                citations=record.citations,
                created_at=record.created_at,
            )
        if isinstance(record, ImageRecord):
            return ImageHistory(
                prompt=record.prompt,
                model=record.model,
                mime_type=record.mime_type,
                image_bytes=record.image_bytes,
                created_at=record.created_at,
            )
        if isinstance(record, CapstoneTaskRecord):
            return CapstoneTaskHistory(
                task_text=record.task_text,
                final_answer=record.final_answer,
                tools_invoked=record.tools_invoked,
                sources=record.sources,
                step_limit_reached=record.step_limit_reached,
                created_at=record.created_at,
            )
        if isinstance(record, CapstoneIngestRecord):
            return CapstoneIngestHistory(
                documents=record.documents,
                created_at=record.created_at,
            )
        raise TypeError(f"Unsupported record type: {type(record).__name__}")

    # -- read -------------------------------------------------------------- #
    def list_records(self, project: ProjectId) -> list[HistorySummary]:
        """Return newest-first summaries (id, timestamp, short label).

        For :data:`ProjectId.CAPSTONE` the task-run and ingestion records are merged
        and sorted newest-first; each summary's ``id`` is the ``kind``-discriminated
        string id (``"task:<n>"`` / ``"ingest:<n>"``) so the detail lookup is
        unambiguous (BUG-003). Every other project uses the plain integer id.
        """
        with self._begin() as session:
            if project is ProjectId.CAPSTONE:
                return self._list_capstone(session)
            return [self._summary_of(project, row) for row in self._list_rows(session, project)]

    def get_record(self, project: ProjectId, record_id: SavedId) -> HistoryRecord | None:
        """Return the full persisted record for ``record_id``, or ``None``.

        For :data:`ProjectId.CAPSTONE`, ``record_id`` is the ``kind``-discriminated
        string id from :meth:`save_record` / :meth:`list_records` (``"task:<n>"`` /
        ``"ingest:<n>"``); unknown or malformed capstone ids return ``None``. Every
        other project takes the plain integer id.
        """
        with self._begin() as session:
            if project is ProjectId.SUPPORT:
                return self._get_chat_session(session, record_id)
            if project is ProjectId.CAPSTONE:
                return self._get_capstone(session, record_id)
            orm_class = _SINGLE_TABLE[project]
            row = session.get(orm_class, record_id)
            return self._row_to_record(project, row) if row is not None else None

    # -- read helpers ------------------------------------------------------ #
    def _list_rows(self, session: Session, project: ProjectId) -> list[Base]:
        if project is ProjectId.SUPPORT:
            orm_class: type[Base] = ChatSessionHistory
        else:
            orm_class = _SINGLE_TABLE[project]
        return list(
            session.execute(
                select(orm_class).order_by(orm_class.id.desc())
            ).scalars()
        )

    def _list_capstone(self, session: Session) -> list[HistorySummary]:
        summaries: list[HistorySummary] = []
        for row in session.execute(
            select(CapstoneTaskHistory).order_by(CapstoneTaskHistory.id.desc())
        ).scalars():
            summaries.append(
                HistorySummary(
                    id=_capstone_id("task", row.id),
                    created_at=row.created_at,
                    label=_truncate(row.task_text),
                )
            )
        for row in session.execute(
            select(CapstoneIngestHistory).order_by(CapstoneIngestHistory.id.desc())
        ).scalars():
            label = "ingest: " + ", ".join(row.documents)
            summaries.append(
                HistorySummary(
                    id=_capstone_id("ingest", row.id),
                    created_at=row.created_at,
                    label=_truncate(label),
                )
            )
        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries

    def _summary_of(self, project: ProjectId, row: Base) -> HistorySummary:
        label = {
            ProjectId.PLAYGROUND: lambda: row.prompt,
            ProjectId.SUPPORT: lambda: row.session_id,
            ProjectId.WEB_AGENT: lambda: row.question,
            ProjectId.DEEP_RESEARCH: lambda: row.topic,
            ProjectId.IMAGE: lambda: row.prompt,
        }[project]()
        return HistorySummary(id=int(row.id), created_at=row.created_at, label=_truncate(label))

    def _get_chat_session(self, session: Session, record_id: SavedId) -> ChatTurnRecord | None:
        row = session.get(ChatSessionHistory, record_id)
        if row is None:
            return None
        # Return the most recent turn's content alongside the session id. The full
        # turn list is available via the relationship for the detail view; the
        # tagged-union variant carries the session identifier (Requirement 12.6).
        turns = row.turns
        last = turns[-1] if turns else None
        return ChatTurnRecord(
            session_id=row.session_id,
            user_message=last.user_message if last else "",
            assistant_reply=last.assistant_reply if last else "",
            created_at=row.created_at,
        )

    def _get_capstone(self, session: Session, record_id: SavedId) -> HistoryRecord | None:
        """Fetch a capstone record by its ``kind``-discriminated id (BUG-003).

        ``record_id`` must be a ``"task:<n>"`` / ``"ingest:<n>"`` string; the prefix
        selects the correct table so a task row and an ingest row sharing the same
        numeric id never shadow each other. Unknown or malformed ids return
        ``None``.
        """
        parsed = _parse_capstone_id(record_id)
        if parsed is None:
            return None
        orm_class, numeric_id = parsed
        row = session.get(orm_class, numeric_id)
        return self._row_to_record(ProjectId.CAPSTONE, row) if row is not None else None

    @staticmethod
    def _row_to_record(project: ProjectId, row: Base) -> HistoryRecord:
        if isinstance(row, PlaygroundHistory):
            return PlaygroundRecord(
                prompt=row.prompt,
                system_prompt=row.system_prompt,
                temperature=row.temperature,
                max_tokens=row.max_tokens,
                model=row.model,
                response_text=row.response_text,
                usage=row.usage,
                created_at=row.created_at,
            )
        if isinstance(row, WebAgentHistory):
            return WebAgentRecord(
                question=row.question,
                answer=row.answer,
                citations=row.citations,
                created_at=row.created_at,
            )
        if isinstance(row, DeepResearchHistory):
            return DeepResearchRecord(
                topic=row.topic,
                sub_questions=row.sub_questions,
                report=row.report,
                citations=row.citations,
                created_at=row.created_at,
            )
        if isinstance(row, ImageHistory):
            return ImageRecord(
                prompt=row.prompt,
                model=row.model,
                image_bytes=bytes(row.image_bytes),
                mime_type=row.mime_type,
                created_at=row.created_at,
            )
        if isinstance(row, CapstoneTaskHistory):
            return CapstoneTaskRecord(
                task_text=row.task_text,
                final_answer=row.final_answer,
                tools_invoked=row.tools_invoked,
                sources=row.sources,
                step_limit_reached=row.step_limit_reached,
                created_at=row.created_at,
            )
        if isinstance(row, CapstoneIngestHistory):
            return CapstoneIngestRecord(documents=row.documents, created_at=row.created_at)
        raise TypeError(f"Unsupported row type: {type(row).__name__}")  # pragma: no cover

    # -- session plumbing -------------------------------------------------- #
    def _begin(self):
        """A transactional scope around one unit of work (commit/rollback/close)."""
        return _Unit(self._session_factory)


# Single-table projects -> their ORM class (chatbot + capstone handled specially).
_SINGLE_TABLE: dict[ProjectId, type[Base]] = {
    ProjectId.PLAYGROUND: PlaygroundHistory,
    ProjectId.WEB_AGENT: WebAgentHistory,
    ProjectId.DEEP_RESEARCH: DeepResearchHistory,
    ProjectId.IMAGE: ImageHistory,
}


class _Unit:
    """Context manager: commit on success, rollback on error, always close."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> Session:
        self._session = self._session_factory()
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self._session is not None
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()
        return False
