"""Instructions for the session agent: for every project and per project

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("agent_instructions", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("projects", "agent_instructions")
    op.drop_column("agent_settings", "instructions")
