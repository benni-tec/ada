from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.analysis import Rows
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.runs import Run, Snapshot
from ada.core.models.time import TimeRange


class RunService(Protocol):
    async def start(
        self,
        project_id: Id,
        actor: Actor,
        time_range: TimeRange | None = None,
        bindings: dict[str, OperatorId] | None = None,
    ) -> Run:
        """A new run. Bindings are checked against the schemas of the input slots they
        name; a mismatch raises Invalid."""
        ...

    async def get(self, id: Id) -> Run: ...
    async def list(self, project_id: Id, limit: int = 50) -> Sequence[Run]: ...

    async def execute(self, run_id: Id, operator_id: OperatorId) -> Run:
        """Make the operator's output available in the run. For every materializing
        operator upstream this reuses the current snapshot when its definition and
        effective parameters match, and creates one otherwise; either way the run fixes
        the snapshot it used. Pass-through operators store nothing."""
        ...

    async def read(self, run_id: Id, operator_id: OperatorId, limit: int = 1000) -> Rows:
        """The operator's output in the run, executing it first if needed. Chains of
        pass-through operators are answered by one query over the snapshots below them."""
        ...

    async def query(self, run_id: Id, operator_id: OperatorId, sql: str, limit: int) -> Rows:
        """`sql` over the operator's output in the run, which it names input_0: a question
        about that output that is not an operator itself, such as an alert rule's
        condition. At most `limit` rows."""
        ...

    async def feed(
        self, run_id: Id, input_id: OperatorId, from_run_id: Id, operator_id: OperatorId, sql: str
    ) -> Run:
        """Fix, as the input operator's data in `run_id`, the rows of `sql` over the
        operator's output in `from_run_id`: e.g. an alert pipeline run on the rows that
        raised the alert. The rows are stored as a snapshot of the input for that run."""
        ...

    async def snapshot(self, id: Id) -> Snapshot:
        """A stored snapshot: when it was fetched, its content hash and row count. A run's
        `snapshots` names the ones it fixed, by id only; this is how a client shows them."""
        ...
