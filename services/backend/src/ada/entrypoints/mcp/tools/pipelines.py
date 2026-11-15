from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from pydantic import Field

from ada.core.models.analysis import Rows
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import Operator, OperatorId
from ada.core.models.pipelines import Pipeline
from ada.core.models.schema import Column, Roles
from ada.core.models.statistics import described
from ada.core.services.ports.batches import BatchService, Step
from ada.core.services.ports.exploration import (
    MAX_EXPLORATION_ROWS,
    Clauses,
    ExplorationService,
)
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.bounds import bound_rows
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.links import widget_url
from ada.entrypoints.mcp.sessions import SessionId

# A preview is for looking at, not for analysing: the agent computes in SQL instead.
MAX_PREVIEW_ROWS = 100

# Said with every exploration's rows, so it is in front of the agent when it reads them.
EXPLORATION_NOTE = (
    "For your own exploration only. Do not show or quote these rows to the person: "
    "anything you present must come from a transform and a widget, so it can be traced."
)


ADD_STATISTIC = f"""Add a statistic over one earlier operator: a named analysis the \
platform has vetted, so its formula is right and its result is traced like a transform's. \
Prefer it to writing the same statistics in SQL. `input` is the operator, `arguments` \
name its columns. The statistic is compiled to SQL, stored with the operator and shown in \
its lineage; a trend's confidence interval is declared as the measure's bounds. The \
statistics:
{described()}

Give a one-line `note` on why you add it: the session shows it. Returns the operator with \
its id and output columns."""


class PreviewRows(Rows):
    dropped_rows: int = 0


class Preview(DomainModel):
    operator_id: OperatorId
    run_id: Id
    rows: PreviewRows


class QueryAnswer(DomainModel):
    columns: tuple[Column, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool
    dropped_rows: int = 0
    # The run the rows were read in; null when they came from one snapshot.
    run_id: Id | None
    note: str = EXPLORATION_NOTE


class BuiltWidget(DomainModel):
    id: Id
    # Where a person sees it in the frontend, relative to the host serving ADA.
    url: str


class Built(DomainModel):
    # Each step's ref: the source id, operator id or widget id it stands for.
    refs: dict[str, str]
    widgets: Sequence[BuiltWidget]


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def add_source_operator(
        project_id: Id,
        session_id: SessionId,
        data_source_id: Id,
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        note: str = "",
    ) -> Operator:
        """Start a pipeline from a registered data source: adds an operator that reads
        it. Use the returned operator id as an input of add_transform, or to preview it.
        Adding the same source twice returns the operator that already exists.

        Give a one-line `note` on why you need this source: the session shows it.
        Returns the operator with its id and output columns."""
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_source(project_id, data_source_id, actor)
        await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool
    @inject
    async def add_history(
        project_id: Id,
        session_id: SessionId,
        source_id: Id,
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        last: Annotated[int, Field(ge=1)] = 10,
        note: str = "",
    ) -> Operator:
        """All stored snapshots of a source, newest first, with snapshot_at and
        snapshot_rank, for comparing over time. `last` limits snapshots (default 10).
        Missing columns are NULL; period (pushdown) sources are unsupported.
        Use the returned operator id as an input of add_transform.
        """
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_history(project_id, source_id, actor, last=last)
        await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool
    @inject
    async def add_transform(
        project_id: Id,
        session_id: SessionId,
        sql: str,
        inputs: Sequence[OperatorId],
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        roles: Roles | None = None,
        materialize: bool = False,
        note: str = "",
    ) -> Operator:
        """Add a SQL step over earlier operators. In the SQL the inputs are the tables
        input_0, input_1, ... in the order of `inputs`. The output columns are worked out
        from the query, so a wrong query is rejected here, before anything runs. The SQL is
        DuckDB's. A wide table with one column per year (or per category) becomes one row
        per value with UNPIVOT, e.g.
        `SELECT region, CAST(year AS INTEGER) AS year, value FROM (UNPIVOT input_0 ON
        COLUMNS(* EXCLUDE (region)) INTO NAME year VALUE value)`.

        `roles` says which output columns are the period, the region code and the measures
        with their confidence bounds; declare them when later steps or widgets depend on it.
        A step whose SQL aggregates rows (GROUP BY, an aggregate or window function,
        DISTINCT, UNION) may not declare a measure with bounds (`lower`, `upper`): the
        interval of an aggregate is not an aggregate of the intervals. Declare the measure
        without bounds instead. A time role's `grain` (year, quarter, month) says what
        every period spans.
        `materialize` stores the result instead of recomputing it; leave it off unless the
        step is expensive. The same SQL over the same inputs returns the existing operator.

        Give a one-line `note` on why you add this step: the session shows it.
        Returns the operator with its id and output columns."""
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_transform(
            project_id, sql, tuple(inputs), actor, roles=roles, materialize=materialize
        )
        await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool(description=ADD_STATISTIC)
    @inject
    async def add_statistic(
        project_id: Id,
        session_id: SessionId,
        tool: str,
        input: OperatorId,
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
        sessions: FromDishka[SessionService],
        arguments: JsonObject | None = None,
        materialize: bool = False,
        note: str = "",
    ) -> Operator:
        await projects.get(project_id)
        actor = calling_agent()
        operator = await pipelines.add_statistic(
            project_id, tool, arguments or {}, input, actor, materialize=materialize
        )
        await sessions.record_operator(session_id, operator.id, note, actor)
        return operator

    @mcp.tool
    @inject
    async def list_pipelines(
        project_id: Id,
        session_id: SessionId,
        projects: FromDishka[ProjectService],
        pipelines: FromDishka[PipelineService],
    ) -> Sequence[Pipeline]:
        """List a project's pipelines: the operators nothing else builds on yet, newest
        first, each with a readable name, its kind, the data sources it reads and its
        output columns. Look here before building: extend or show an existing pipeline
        rather than reading the same source again."""
        await projects.get(project_id)
        return await pipelines.pipelines(project_id)

    @mcp.tool
    @inject
    async def get_lineage(
        session_id: SessionId, operator_id: OperatorId, pipelines: FromDishka[PipelineService]
    ) -> Sequence[Operator]:
        """Show how an operator's output is made: the operator and everything upstream of
        it, inputs first, each with its parameters (the SQL, the data source) and output
        columns. Use it to understand or explain a result, or to check a pipeline before
        putting it in a widget."""
        return await pipelines.lineage(operator_id)

    @mcp.tool
    @inject
    async def preview_operator(
        session_id: SessionId,
        operator_id: OperatorId,
        pipelines: FromDishka[PipelineService],
        runs: FromDishka[RunService],
        limit: Annotated[int, Field(ge=1, le=MAX_PREVIEW_ROWS)] = 10,
    ) -> Preview:
        """Look at the first rows of an operator's output, to check that a source loaded
        or a transform does what you meant. Runs the pipeline with no bindings and an open
        time range. Returns the column names and types and at most `limit` rows
        (`truncated` says whether there are more), never the whole dataset: use SQL in a
        transform to aggregate. String cells are cut after 300 characters; the result is
        capped at 20 KB. `dropped_rows` counts rows omitted by that budget."""
        operator = await pipelines.get(operator_id)
        run = await runs.start(operator.project_id, calling_agent())
        rows = await runs.read(run.id, operator_id, limit)
        return bound_rows(
            Preview(
                operator_id=operator_id,
                run_id=run.id,
                rows=PreviewRows(**rows.model_dump()),
            ),
            nested=True,
        )

    @mcp.tool
    @inject
    async def query_operator(
        session_id: SessionId,
        operator_id: OperatorId,
        select: str,
        exploration: FromDishka[ExplorationService],
        where: str | None = None,
        group_by: str | None = None,
        having: str | None = None,
        order_by: str | None = None,
        limit: Annotated[int, Field(ge=1, le=MAX_EXPLORATION_ROWS)] = 100,
        run_id: Id | None = None,
        snapshot_id: Id | None = None,
    ) -> QueryAnswer:
        """Explore any operator's output, sources included, with one SQL query, before
        you decide what to build: which values a column has, how many rows per year,
        whether a join would match. The rows are for you only: never show or quote them
        to the person. Anything you present must come from a transform and a widget, so
        it can be traced.

        Give each clause as an SQL fragment without its keyword. They are put together as
        `SELECT {select} FROM input_0 WHERE {where} GROUP BY {group_by} HAVING {having}
        ORDER BY {order_by} LIMIT {limit}`, where input_0 is the operator's output; window
        functions are allowed in `select`. Only that one SELECT runs, and nothing is
        stored. E.g. select "year, count(*) AS n", group_by "year", order_by "year".

        Reads the output in `run_id`, or in `snapshot_id` (a stored snapshot of this
        operator, if it is a source or a materialized transform), or by default in a new
        run with no bindings and an open time range. Returns the columns, at most `limit`
        rows (`truncated` says whether there are more) and the run it read. String cells
        are cut after 300 characters; the result is capped at 20 KB. `dropped_rows` counts
        rows omitted by that budget. Use SQL to aggregate or select a smaller excerpt."""
        explored = await exploration.query(
            operator_id,
            Clauses(
                select=select,
                where=where,
                group_by=group_by,
                having=having,
                order_by=order_by,
            ),
            calling_agent(),
            limit=limit,
            run_id=run_id,
            snapshot_id=snapshot_id,
        )
        return bound_rows(
            QueryAnswer(
                columns=explored.rows.columns,
                rows=explored.rows.rows,
                truncated=explored.rows.truncated,
                run_id=explored.run_id,
            )
        )

    @mcp.tool
    @inject
    async def build_pipeline(
        project_id: Id,
        session_id: SessionId,
        steps: Sequence[Step],
        batches: FromDishka[BatchService],
    ) -> Built:
        """Build a whole pipeline in one call: register sources, read them, add input
        slots and SQL steps, and show results as widgets. Prefer it to calling the single
        tools one by one. Each step is one of:

        - `{"ref": "s", "register_source": {...the fields of register_source...,
          "refresh": true}}`: `refresh` fetches the data once the batch is stored; the
          steps after it are checked against `declared_schema`, so declare it.
        - `{"ref": "src", "source_operator": {"data_source_id": "$s"}}`
        - `{"ref": "slot", "input": {"name": "...", "output": {schema}, "default": "$t"}}`
        - `{"ref": "t", "transform": {"sql": "...", "inputs": ["$src"], "roles": {...},
          "materialize": false}}`, as add_transform.
        - `{"ref": "w", "widget": {"operator": "$t", "type": "...", "title": "...",
          "spec": {...}}}`, as create_widget.

        "$name" stands for what the earlier step with that `ref` made (a registered
        source also stands for its source operator); any other value is an existing id.
        Every step may carry a one-line `note`, shown in the session, as the single
        tools show it.

        It is all or nothing: the first step that fails is named by its index and ref,
        and nothing of the batch is stored. Running the same batch again creates nothing
        twice. Returns `refs` (each ref's source, operator or widget id) and the widgets
        with their `url`: give the urls to the person."""
        built = await batches.build(project_id, steps, calling_agent(), session_id=session_id)
        return Built(
            refs=built.refs,
            widgets=[BuiltWidget(id=w.id, url=widget_url(w)) for w in built.widgets],
        )
