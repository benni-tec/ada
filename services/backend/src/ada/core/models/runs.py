from datetime import datetime

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id
from ada.core.models.operators import OperatorId
from ada.core.models.time import Interval, TimeRange

# Run id plus operator id addresses any intermediate result.


class Snapshot(DomainModel):
    """The stored output of a materializing operator for one set of parameters. Written
    once and never changed; a refresh makes a new snapshot."""

    id: Id
    project_id: Id
    operator_id: OperatorId
    # The parameters the operator actually used, e.g. the period it fetched. Two requests
    # with the same key can share a snapshot.
    parameters_key: str
    period: Interval | None = None
    # Of the stored data. An identical refetch has the same hash, so nothing downstream
    # needs to run again.
    content_hash: str
    # Where the analysis store keeps it.
    location: str
    row_count: int | None = None
    fetched_at: datetime
    # Where the data came from, as the reader reported it: the final URL with its query.
    origin: str | None = None
    # Set when a newer snapshot for the same operator and key replaced this one.
    superseded_at: datetime | None = None


class Run(DomainModel):
    """One execution of a pipeline for a set of parameters. It fixes which snapshot each
    materializing operator uses, so everything read through the run is one consistent
    state. Immutable."""

    id: Id
    project_id: Id
    time_range: TimeRange = TimeRange()
    # Input slot name to the operator bound to it. Binding a slot to another operator
    # composes pipelines into a DAG: whatever reads the slot reads that operator instead.
    bindings: dict[str, OperatorId] = {}
    # Materializing operator to the snapshot this run uses.
    snapshots: dict[OperatorId, Id] = {}
    started_by: Actor
    started_at: datetime

    @property
    def is_scenario(self) -> bool:
        """The run binds at least one input slot. The name is historical (from a dropped
        scenarios plan) and kept for API compatibility; it does not mean the numbers are
        simulated."""
        return bool(self.bindings)
