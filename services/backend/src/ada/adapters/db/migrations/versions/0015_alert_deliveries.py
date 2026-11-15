"""Alert channel delivery history."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("alerts.id", ondelete="CASCADE")),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Uuid(),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("test", sa.Boolean(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_deliveries_project_id", "alert_deliveries", ["project_id"])


def downgrade() -> None:
    op.drop_table("alert_deliveries")
