"""When each agent turn started, and whether its end was announced

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_turns", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_turns",
        sa.Column("settled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # Turns that ended before this were announced then; one still running gets its start
    # from its creation, so it is recovered once it is overdue by that.
    op.execute("UPDATE agent_turns SET settled = true WHERE status NOT IN ('queued', 'running')")
    op.execute("UPDATE agent_turns SET started_at = created_at WHERE status = 'running'")
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
