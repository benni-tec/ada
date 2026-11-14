from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.analysis import Rows
from ada.core.models.base import DomainModel, Id
from ada.core.models.operators import Operator, OperatorId
from ada.core.models.schema import Roles
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject

# A preview is for looking at, not for analysing: the agent computes in SQL instead.
MAX_PREVIEW_ROWS = 100


class Preview(DomainModel):
    operator_id: OperatorId
    run_id: Id
    rows: Rows


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def add_source_operator(
        project_id: Id,
        data_source_id: Id,
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        session_id: Id | None = None,
        note: str = "",
    ) -> Operator:
        """Start a pipeline from a registered data source: adds an operator that reads
        it. Use the returned operator id as an input of add_transform, or to preview it.
        Adding the same source twice returns the operator that already exists.

        Pass `session_id` and a one-line `note` on why you need this source to show it in
        that session. Returns the operator with its id and output columns."""
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_source(project_id, data_source_id, actor)
        if session_id is not None:
            await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool
    @inject
    async def add_transform(
        project_id: Id,
        sql: str,
        inputs: Sequence[OperatorId],
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        roles: Roles | None = None,
        materialize: bool = False,
        session_id: Id | None = None,
        note: str = "",
    ) -> Operator:
        """Add a SQL step over earlier operators. In the SQL the inputs are the tables
        input_0, input_1, ... in the order of `inputs`. The output columns are worked out
        from the query, so a wrong query is rejected here, before anything runs.

        `roles` says which output columns are the period, the region code and the measures
        with their confidence bounds; declare them when later steps or widgets depend on it.
        `materialize` stores the result instead of recomputing it; leave it off unless the
        step is expensive. The same SQL over the same inputs returns the existing operator.

        Pass `session_id` and a one-line `note` on why you add this step to show it in that
        session. Returns the operator with its id and output columns."""
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_transform(
            project_id, sql, tuple(inputs), actor, roles=roles, materialize=materialize
        )
        if session_id is not None:
            await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool
    @inject
    async def get_lineage(
        operator_id: OperatorId, pipelines: FromDishka[PipelineService]
    ) -> Sequence[Operator]:
        """Show how an operator's output is made: the operator and everything upstream of
        it, inputs first, each with its parameters (the SQL, the data source) and output
        columns. Use it to understand or explain a result, or to check a pipeline before
        putting it in a widget."""
        return await pipelines.lineage(operator_id)

    @mcp.tool
    @inject
    async def preview_operator(
        operator_id: OperatorId,
        pipelines: FromDishka[PipelineService],
        runs: FromDishka[RunService],
        limit: Annotated[int, Field(ge=1, le=MAX_PREVIEW_ROWS)] = 10,
    ) -> Preview:
        """Look at the first rows of an operator's output, to check that a source loaded
        or a transform does what you meant. Runs the pipeline with no bindings and an open
        time range. Returns the column names and types and at most `limit` rows
        (`truncated` says whether there are more), never the whole dataset: use SQL in a
        transform to aggregate."""
        operator = await pipelines.get(operator_id)
        run = await runs.start(operator.project_id, calling_agent())
        return Preview(
            operator_id=operator_id, run_id=run.id, rows=await runs.read(run.id, operator_id, limit)
        )
