"""Optional per-source monitor interval; existing monitors keep their schedule."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_sources", sa.Column("check_every", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("data_sources", "check_every")
