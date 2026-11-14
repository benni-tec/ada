"""Provenance, monitors, child sessions and the research model

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("data_sources", sa.Column("monitor_id", sa.Text(), nullable=True))
    op.add_column("data_sources", sa.Column("monitor_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("snapshots", sa.Column("origin", sa.Text(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("agent", sa.String(length=16), server_default="session", nullable=False),
    )
    op.add_column("sessions", sa.Column("parent_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sessions", sa.Column("web_calls", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index(
        op.f("ix_sessions_parent_session_id"), "sessions", ["parent_session_id"], unique=False
    )
    op.create_foreign_key(
        "fk_sessions_parent_session_id",
        "sessions",
        "sessions",
        ["parent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("agent_settings", sa.Column("research_agent_model_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_settings_research_agent_model_id",
        "agent_settings",
        "llm_models",
        ["research_agent_model_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_settings_research_agent_model_id", "agent_settings", type_="foreignkey"
    )
    op.drop_column("agent_settings", "research_agent_model_id")
    op.drop_constraint("fk_sessions_parent_session_id", "sessions", type_="foreignkey")
    op.drop_index(op.f("ix_sessions_parent_session_id"), table_name="sessions")
    op.drop_column("sessions", "web_calls")
    op.drop_column("sessions", "parent_session_id")
    op.drop_column("sessions", "agent")
    op.drop_column("snapshots", "origin")
    op.drop_column("data_sources", "monitor_secret_encrypted")
    op.drop_column("data_sources", "monitor_id")
    op.drop_column("data_sources", "provenance")
