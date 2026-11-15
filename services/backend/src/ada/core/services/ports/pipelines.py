from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.operators import Operator, OperatorId
from ada.core.models.pipelines import Pipeline
from ada.core.models.schema import Column, Roles, Schema


class PipelineService(Protocol):
    """Builds pipelines one operator at a time. Every method that adds an operator works
    out or checks its output schema before anything runs, and returns the existing
    operator when the same definition was added before."""

    async def add_source(self, project_id: Id, data_source_id: Id, actor: Actor) -> Operator:
        """An operator that reads a registered data source. Its schema is the source's
        declared one, or is read from the data on first use."""
        ...

    async def add_history(
        self, project_id: Id, source_id: Id, actor: Actor, last: int = 10
    ) -> Operator:
        """Stored whole-source snapshots, newest first, with snapshot_at and snapshot_rank.
        The run's fixed source snapshot bounds history; row time ranges do not filter it.
        Differing columns are unioned by name, with missing values filled with NULL.
        Period sources and source columns named snapshot_at or snapshot_rank are refused.
        """
        ...

    async def add_transform(
        self,
        project_id: Id,
        sql: str,
        inputs: Sequence[OperatorId],
        actor: Actor,
        roles: Roles | None = None,
        materialize: bool = False,
    ) -> Operator:
        """SQL over earlier operators, which it names input_0, input_1, ... Its columns are
        derived by describing the query; `roles` declares what they mean and must name
        only columns the query returns. Raises Invalid otherwise."""
        ...

    async def add_statistic(
        self,
        project_id: Id,
        tool: str,
        arguments: JsonObject,
        input: OperatorId,
        actor: Actor,
        materialize: bool = False,
    ) -> Operator:
        """A named statistic over one earlier operator (statistics.py): its arguments are
        checked against the input's columns and it is compiled to SQL, stored with it.
        Raises Invalid for an unknown statistic or arguments that do not fit."""
        ...

    async def describe(
        self, project_id: Id, sql: str, inputs: Sequence[OperatorId]
    ) -> tuple[Column, ...]:
        """The columns SQL over these operators (input_0, input_1, ...) would return,
        without adding an operator. Raises Invalid when it does not bind."""
        ...

    async def add_input(
        self, project_id: Id, name: str, output: Schema, default: OperatorId, actor: Actor
    ) -> Operator:
        """A named slot with a declared schema, bound to `default` unless a run binds it
        to something else."""
        ...

    async def get(self, id: OperatorId) -> Operator: ...

    async def lineage(self, id: OperatorId) -> Sequence[Operator]:
        """The operator's pipeline: itself and everything upstream, inputs first."""
        ...

    async def pipelines(self, project_id: Id) -> Sequence[Pipeline]:
        """The project's pipelines: operators that no other operator uses as an input,
        newest first, each with a readable name and the data sources it reads."""
        ...
