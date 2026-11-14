"""Widgets read further operators by name, and keep what went wrong drawing them

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-14 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("widgets", sa.Column("render_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("widgets", "render_error")
    op.drop_column("widgets", "inputs")
