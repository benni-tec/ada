import re

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.operators import OperatorId
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.repositories import OperatorRepository, SnapshotRepository
from ada.core.services.pipelines.fusion import QueryNode, SnapshotNode, compose
from ada.core.services.ports.exploration import (
    MAX_EXPLORATION_ROWS,
    Clauses,
    ExplorationService,
    Explored,
)
from ada.core.services.ports.runs import RunService

# Each clause with the keyword that introduces it. A fragment that starts with its own
# keyword anyway ("WHERE x > 1") has it taken off, so it is not written twice.
_KEYWORDS = (
    ("select", "SELECT"),
    ("where", "WHERE"),
    ("group_by", "GROUP BY"),
    ("having", "HAVING"),
    ("order_by", "ORDER BY"),
)


def assemble(clauses: Clauses) -> str:
    """`SELECT {select} FROM input_0 [WHERE ...] [GROUP BY ...] [HAVING ...] [ORDER BY ...]`.
    Each fragment goes on its own line, so a trailing comment in one ends with its line.
    The limit is not written here: the store applies it, one row over, to tell whether
    there is more."""
    lines: list[str] = []
    for field, keyword in _KEYWORDS:
        fragment = getattr(clauses, field)
        if fragment is None:
            continue
        pattern = r"\s*" + r"\s+".join(keyword.split()) + r"\b"
        fragment = re.sub(f"^{pattern}", "", fragment, flags=re.IGNORECASE).strip()
        if not fragment:
            if field == "select":
                raise Invalid("A query needs `select`: the columns or expressions to return")
            continue
        lines.append(f"{keyword} {fragment}")
        if field == "select":
            lines.append("FROM input_0")
    return "\n".join(lines)


class Exploration(ExplorationService):
    """Questions about an operator's output that are not operators themselves. The SQL
    runs in the analysis store, which takes exactly one SELECT and nothing else, as it
    does for transforms; nothing is stored."""

    def __init__(
        self,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        runs: RunService,
        store: AnalysisStore,
    ) -> None:
        self.operators = operators
        self.snapshots = snapshots
        self.runs = runs
        self.store = store

    async def query(
        self,
        operator_id: OperatorId,
        clauses: Clauses,
        actor: Actor,
        limit: int = 100,
        run_id: Id | None = None,
        snapshot_id: Id | None = None,
    ) -> Explored:
        if not 1 <= limit <= MAX_EXPLORATION_ROWS:
            raise Invalid(f"The limit is between 1 and {MAX_EXPLORATION_ROWS}")
        if run_id is not None and snapshot_id is not None:
            raise Invalid("Read either in a run or in a snapshot, not both")
        sql = assemble(clauses)
        operator = await self.operators.get(operator_id)
        if snapshot_id is not None:
            snapshot = await self.snapshots.get(snapshot_id)
            if snapshot.operator_id != operator.id:
                raise Invalid(f"Snapshot {snapshot_id} is not one of operator {operator_id}")
            node = QueryNode("explored", sql, (SnapshotNode(snapshot),))
            return Explored(rows=await self.store.run(compose(node), limit), run_id=None)
        if run_id is None:
            run_id = (await self.runs.start(operator.project_id, actor)).id
        rows = await self.runs.query(run_id, operator.id, sql, limit)
        return Explored(rows=rows, run_id=run_id)
