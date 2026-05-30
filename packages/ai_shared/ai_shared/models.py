"""SQLAlchemy 2.x ORM models for the shared History_Store (Requirement 12).

Every completed operation across the six mini-projects is persisted as a row in
one of the project-scoped tables defined here. The tables are created and upgraded
via Alembic (``packages/ai_shared/migrations``), never by implicit ``create_all``
in production — though tests may call ``Base.metadata.create_all`` against an
ephemeral database.

Shared schema invariants (design "Persistent History Schema (PostgreSQL)"):

- Every table carries a surrogate integer primary key ``id`` and a
  ``created_at TIMESTAMPTZ NOT NULL DEFAULT now()`` (the creation timestamp
  required by Requirement 12.1).
- There is **no expiry column and no row cap** — records are retained until a
  developer explicitly deletes them (Requirement 12.2).
- Structured sub-objects (token usage, citations, sub-questions, the report,
  tool invocations, sources, document names) are stored as ``JSONB`` so they
  round-trip exactly without extra join tables.
- The chatbot is modeled relationally (``ChatSessionHistory`` 1—N
  ``ChatTurnHistory``) so individual turns are browsable (Requirement 12.6).
- The generated image is stored durably as raw bytes in a ``BYTEA`` column
  (``LargeBinary``) alongside its MIME type (Requirement 12.9), keeping the
  History_Store self-contained.

This module is deliberately named ``models.py`` (the LLM message/stream types live
in :mod:`ai_shared.llm_types`, so there is no collision). Importing it requires no
live database connection — it only declares table metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "Base",
    "PlaygroundHistory",
    "ChatSessionHistory",
    "ChatTurnHistory",
    "WebAgentHistory",
    "DeepResearchHistory",
    "ImageHistory",
    "CapstoneTaskHistory",
    "CapstoneIngestHistory",
    "ALL_TABLES",
]


class Base(DeclarativeBase):
    """Declarative base for every History_Store table."""


# A reusable ``TIMESTAMPTZ NOT NULL DEFAULT now()`` mapping for ``created_at``.
# ``DateTime(timezone=True)`` renders to ``TIMESTAMP WITH TIME ZONE`` (TIMESTAMPTZ)
# on PostgreSQL; ``server_default=func.now()`` makes the database stamp the row.
def _created_at_column() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PlaygroundHistory(Base):
    """LLM Playground run (Requirement 12.5)."""

    __tablename__ = "playground_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    # {"prompt_tokens", "output_tokens", "total_tokens"}
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


class ChatSessionHistory(Base):
    """Support Chatbot session — relational parent of its turns (Requirement 12.6)."""

    __tablename__ = "chat_session_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()

    turns: Mapped[list["ChatTurnHistory"]] = relationship(
        back_populates="session",
        order_by="ChatTurnHistory.id",
        cascade="all, delete-orphan",
    )


class ChatTurnHistory(Base):
    """A single Support Chatbot turn, linked to its session (Requirement 12.6)."""

    __tablename__ = "chat_turn_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_pk: Mapped[int] = mapped_column(
        ForeignKey("chat_session_history.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_reply: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()

    session: Mapped["ChatSessionHistory"] = relationship(back_populates="turns")


class WebAgentHistory(Base):
    """Ask-the-Web answer (Requirement 12.7)."""

    __tablename__ = "web_agent_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"url", "title"}] — source URLs drawn from the retrieved results.
    citations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


class DeepResearchHistory(Base):
    """Deep Research report (Requirement 12.8)."""

    __tablename__ = "deep_research_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"id", "text"}]
    sub_questions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # {"title", "introduction", "sections": [...], "conclusion"}
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # [{"url", "title"}]
    citations: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


class ImageHistory(Base):
    """Image generation (Requirement 12.9) — image stored durably as BYTEA."""

    __tablename__ = "image_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    # Raw image bytes — BYTEA on PostgreSQL.
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


class CapstoneTaskHistory(Base):
    """Capstone task run (Requirement 12.10)."""

    __tablename__ = "capstone_task_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_answer: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"tool", "ok", "error"}]
    tools_invoked: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # ["source-doc-name", ...]
    sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    step_limit_reached: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


class CapstoneIngestHistory(Base):
    """Capstone document-ingestion record (Requirement 12.11)."""

    __tablename__ = "capstone_ingest_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ["document-name", ...] — names of the successfully ingested documents.
    documents: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()


#: All ORM table classes, in dependency order (parents before children).
ALL_TABLES: tuple[type[Base], ...] = (
    PlaygroundHistory,
    ChatSessionHistory,
    ChatTurnHistory,
    WebAgentHistory,
    DeepResearchHistory,
    ImageHistory,
    CapstoneTaskHistory,
    CapstoneIngestHistory,
)
