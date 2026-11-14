"""When each agent turn started, and whether its end was announced

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_turns", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_turns",
        sa.Column("settled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Turns that ended before this were announced then. One still running counts from the
    # upgrade: its real start is unknown, and failing a live turn is worse than waiting.
    op.execute("UPDATE agent_turns SET settled = true WHERE status NOT IN ('queued', 'running')")
    op.execute("UPDATE agent_turns SET started_at = now() WHERE status = 'running'")
    op.create_index(
        "ix_agent_turns_unsettled",
        "agent_turns",
        ["status"],
        unique=False,
        postgresql_where=sa.text("NOT settled"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_turns_unsettled",
        table_name="agent_turns",
        postgresql_where=sa.text("NOT settled"),
    )
    op.drop_column("agent_turns", "settled")
    op.drop_column("agent_turns", "started_at")
