from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.analysis import Rows
from ada.core.models.base import DomainModel, Id
from ada.core.models.operators import OperatorId

# A look, not a dataset: an agent aggregates in SQL instead of reading rows.
MAX_EXPLORATION_ROWS = 500


class Clauses(DomainModel):
    """The parts of one SELECT over an operator's output, which the query names input_0.
    Each is an SQL fragment without its keyword; window functions are allowed in
    `select`."""

    select: str
    where: str | None = None
    group_by: str | None = None
    having: str | None = None
    order_by: str | None = None


class Explored(DomainModel):
    rows: Rows
    # The run the rows were read in; None when they came from one stored snapshot.
    run_id: Id | None


class ExplorationService(Protocol):
    async def query(
        self,
        operator_id: OperatorId,
        clauses: Clauses,
        actor: Actor,
        limit: int = 100,
        run_id: Id | None = None,
        snapshot_id: Id | None = None,
    ) -> Explored:
        """`SELECT {select} FROM input_0 [WHERE] [GROUP BY] [HAVING] [ORDER BY]` over the
        operator's output, at most `limit` rows (1 to MAX_EXPLORATION_ROWS). The query is
        held to what a transform may be (one SELECT, nothing else) and stores nothing.

        Reads the output in `run_id`, or in `snapshot_id`, one stored snapshot of this
        operator (a source's or a materialized transform's), or by default in a new run
        with no bindings and an open time range, started by `actor`."""
        ...
