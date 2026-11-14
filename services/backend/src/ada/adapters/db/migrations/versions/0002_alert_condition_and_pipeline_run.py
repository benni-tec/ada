"""Record each alert's condition operator and alert pipeline run

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14 05:12:12.246590
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both nullable: alerts stored before this revision have neither.
    op.add_column("alerts", sa.Column("condition_operator_id", sa.String(length=64), nullable=True))
    op.add_column("alerts", sa.Column("pipeline_run_id", sa.Uuid(), nullable=True))
    # Named as PostgreSQL would name them, so the downgrade can drop them.
    op.create_foreign_key(
        "alerts_condition_operator_id_fkey",
        "alerts",
        "operators",
        ["condition_operator_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "alerts_pipeline_run_id_fkey",
        "alerts",
        "runs",
        ["pipeline_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("alerts_pipeline_run_id_fkey", "alerts", type_="foreignkey")
    op.drop_constraint("alerts_condition_operator_id_fkey", "alerts", type_="foreignkey")
    op.drop_column("alerts", "pipeline_run_id")
    op.drop_column("alerts", "condition_operator_id")
