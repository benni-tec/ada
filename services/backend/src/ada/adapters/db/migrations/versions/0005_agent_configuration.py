"""Agent configuration in the database: providers, models, settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14 08:57:10.640544
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "llm_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model"),
    )
    op.create_table(
        "agent_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_agent_model_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="agent_settings_one_row"),
        sa.ForeignKeyConstraint(["session_agent_model_id"], ["llm_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The one row, so the settings always exist: no session agent yet.
    op.execute(
        "INSERT INTO agent_settings (id, session_agent_model_id, revision) VALUES (1, NULL, 1)"
    )


def downgrade() -> None:
    op.drop_table("agent_settings")
    op.drop_table("llm_models")
    op.drop_table("llm_providers")
