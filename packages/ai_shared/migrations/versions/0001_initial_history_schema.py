"""initial History_Store schema — all six mini-project history tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00.000000+00:00

Creates every project-scoped history table (Requirements 12.2, 12.5–12.11). Each
table has a surrogate ``id`` primary key and ``created_at TIMESTAMPTZ NOT NULL
DEFAULT now()``; there is no expiry column and no row cap (Requirement 12.2).
Structured sub-objects use ``JSONB``; the chatbot is modeled relationally
(sessions 1—N turns); the generated image is stored as ``BYTEA``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reusable column factory for the creation timestamp.
def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    # 12.5 — LLM Playground run
    op.create_table(
        "playground_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # 12.6 — Support Chatbot session + turns (relational)
    op.create_table(
        "chat_session_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_session_history_session_id",
        "chat_session_history",
        ["session_id"],
    )

    op.create_table(
        "chat_turn_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_pk", sa.Integer(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_reply", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["session_pk"],
            ["chat_session_history.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_turn_history_session_pk",
        "chat_turn_history",
        ["session_pk"],
    )

    # 12.7 — Web_Agent ask
    op.create_table(
        "web_agent_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # 12.8 — Deep_Research report
    op.create_table(
        "deep_research_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("sub_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # 12.9 — Image_Service generation (image bytes stored as BYTEA)
    op.create_table(
        "image_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=127), nullable=False),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # 12.10 — Capstone task run
    op.create_table(
        "capstone_task_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_text", sa.Text(), nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=False),
        sa.Column("tools_invoked", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("step_limit_reached", sa.Boolean(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )

    # 12.11 — Capstone ingested-documents record
    op.create_table(
        "capstone_ingest_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("documents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("capstone_ingest_history")
    op.drop_table("capstone_task_history")
    op.drop_table("image_history")
    op.drop_table("deep_research_history")
    op.drop_table("web_agent_history")
    op.drop_index("ix_chat_turn_history_session_pk", table_name="chat_turn_history")
    op.drop_table("chat_turn_history")
    op.drop_index("ix_chat_session_history_session_id", table_name="chat_session_history")
    op.drop_table("chat_session_history")
    op.drop_table("playground_history")
