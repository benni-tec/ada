"""Sessions get attachments; widgets keep a judge's verdict; dashboards and reports an order

The dashboard shown beside a session becomes its first attachment. The column
`sessions.panel_dashboard_id` stays, unused, so this migration only adds.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-14 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column(
        "widgets", sa.Column("verdict", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.create_table(
        "session_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "kind", "ref", name="uq_session_attachments_ref"),
    )
    op.create_index(
        op.f("ix_session_attachments_session_id"), "session_attachments", ["session_id"]
    )
    op.execute(
        """
        INSERT INTO session_attachments (id, session_id, kind, ref, title, actor, created_at)
        SELECT uuidv7(), id, 'dashboard', panel_dashboard_id::text, '',
               '{"kind": "system", "name": ""}'::jsonb, now()
        FROM sessions WHERE panel_dashboard_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_session_attachments_session_id"), table_name="session_attachments")
    op.drop_table("session_attachments")
    op.drop_column("widgets", "verdict")
    op.drop_column("reports", "position")
    op.drop_column("dashboards", "position")
