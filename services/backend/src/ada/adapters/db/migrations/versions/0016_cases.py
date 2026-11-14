"""Case types, cases, their step events and model results; a model's case type

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_case_types_project_id"), "case_types", ["project_id"])
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_type_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_type_id"], ["case_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_type_id", "key"),
    )
    op.create_index(op.f("ix_cases_case_type_id"), "cases", ["case_type_id"])
    op.create_table(
        "case_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_case_events_case_id"), "case_events", ["case_id"])
    op.create_table(
        "case_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("section", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("created_by", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["statistical_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_case_results_case_id"), "case_results", ["case_id"])
    op.create_index(op.f("ix_case_results_model_id"), "case_results", ["model_id"])
    op.add_column("statistical_models", sa.Column("case_type_id", sa.Uuid(), nullable=True))
    op.add_column(
        "statistical_models",
        sa.Column("auto_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_foreign_key(
        "statistical_models_case_type_id_fkey",
        "statistical_models",
        "case_types",
        ["case_type_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_statistical_models_case_type_id"), "statistical_models", ["case_type_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_statistical_models_case_type_id"), table_name="statistical_models")
    op.drop_constraint(
        "statistical_models_case_type_id_fkey", "statistical_models", type_="foreignkey"
    )
    op.drop_column("statistical_models", "auto_run")
    op.drop_column("statistical_models", "case_type_id")
    op.drop_index(op.f("ix_case_results_model_id"), table_name="case_results")
    op.drop_index(op.f("ix_case_results_case_id"), table_name="case_results")
    op.drop_table("case_results")
    op.drop_index(op.f("ix_case_events_case_id"), table_name="case_events")
    op.drop_table("case_events")
    op.drop_index(op.f("ix_cases_case_type_id"), table_name="cases")
    op.drop_table("cases")
    op.drop_index(op.f("ix_case_types_project_id"), table_name="case_types")
    op.drop_table("case_types")
