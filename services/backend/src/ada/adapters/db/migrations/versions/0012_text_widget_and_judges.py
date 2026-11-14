"""The judges' settings: global defaults per kind, and projects' overrides

The text widget needs no schema of its own: its spec is a widget spec, and its verdict
goes in `widgets.verdict`, which 0011 added.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-14 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every kind starts at warn without a model: reviews stay unchecked until one is chosen.
KINDS = ("text_widget", "widget_code")


def upgrade() -> None:
    op.create_table(
        "judge_defaults",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("strictness", sa.String(length=16), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("kind"),
    )
    op.create_table(
        "project_judges",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("strictness", sa.String(length=16), nullable=True),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id", "kind"),
    )
    for kind in KINDS:
        op.execute(
            "INSERT INTO judge_defaults (kind, strictness, model_id, instructions, revision) "
            f"VALUES ('{kind}', 'warn', NULL, '', 1)"
        )


def downgrade() -> None:
    op.drop_table("project_judges")
    op.drop_table("judge_defaults")
