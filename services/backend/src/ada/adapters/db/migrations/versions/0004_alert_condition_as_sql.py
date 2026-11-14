"""Keep each alert's condition as SQL; a rule's condition is no longer an operator

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The operators checks made for rule conditions: transforms the platform made itself
# ("ada" is the only system actor that adds transforms) that an alert names. One that
# something else was built on is kept: it has become part of a pipeline.
CONDITIONS = """
    SELECT DISTINCT a.condition_operator_id AS id FROM alerts a
    JOIN operators o ON o.id = a.condition_operator_id
    WHERE o.kind = 'transform'
      AND o.created_by = '{"kind": "system", "name": "ada"}'::jsonb
      AND NOT EXISTS (SELECT 1 FROM operator_inputs i WHERE i.input_id = o.id)
      AND NOT EXISTS (SELECT 1 FROM widgets w WHERE w.operator_id = o.id)
      AND NOT EXISTS (
          SELECT 1 FROM alert_rules r WHERE o.id IN (r.operator_id, r.alert_pipeline_id)
      )
"""


def upgrade() -> None:
    op.add_column("alerts", sa.Column("condition_sql", sa.Text(), nullable=True))
    op.execute(
        "UPDATE alerts a SET condition_sql = o.params->>'sql' "
        "FROM operators o WHERE o.id = a.condition_operator_id"
    )
    op.execute(f"CREATE TEMP TABLE dropped_conditions AS {CONDITIONS}")
    op.drop_constraint("alerts_condition_operator_id_fkey", "alerts", type_="foreignkey")
    op.drop_column("alerts", "condition_operator_id")
    # Their snapshots and the runs' records of them go with them; the alerts keep the SQL.
    for table, column in (
        ("run_snapshots", "operator_id"),
        ("snapshots", "operator_id"),
        ("operators", "id"),
    ):
        op.execute(f"DELETE FROM {table} WHERE {column} IN (SELECT id FROM dropped_conditions)")
    op.execute("DROP TABLE dropped_conditions")


def downgrade() -> None:
    # The deleted condition operators are not restored; alerts lose the link to them.
    op.add_column("alerts", sa.Column("condition_operator_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "alerts_condition_operator_id_fkey",
        "alerts",
        "operators",
        ["condition_operator_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("alerts", "condition_sql")
