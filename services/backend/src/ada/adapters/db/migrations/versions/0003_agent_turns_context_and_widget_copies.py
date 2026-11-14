"""Agent turns, message context and widget copies

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14 06:45:37.054996
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_entry_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["prompt_entry_id"], ["session_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_turns_session_created", "agent_turns", ["session_id", "created_at"], unique=False
    )
    # Entries stored before this revision are about nothing in particular.
    op.add_column(
        "session_entries",
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("widgets", sa.Column("copied_from", sa.Uuid(), nullable=True))
    # Named as PostgreSQL would name it, so the downgrade can drop it.
    op.create_foreign_key(
        "widgets_copied_from_fkey",
        "widgets",
        "widgets",
        ["copied_from"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("widgets_copied_from_fkey", "widgets", type_="foreignkey")
    op.drop_column("widgets", "copied_from")
    op.drop_column("session_entries", "context")
    op.drop_index("ix_agent_turns_session_created", table_name="agent_turns")
    op.drop_table("agent_turns")
