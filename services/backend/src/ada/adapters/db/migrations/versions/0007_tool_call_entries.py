"""Tool calls in the session record: the session entry's tool call

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Entries of the new kind "tool_call" carry it; the kind column (16 characters) fits it.
    op.add_column(
        "session_entries",
        sa.Column("tool_call", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    # Without their tool call, the entries of that kind would mean nothing.
    op.execute("DELETE FROM session_entries WHERE kind = 'tool_call'")
    op.drop_column("session_entries", "tool_call")
