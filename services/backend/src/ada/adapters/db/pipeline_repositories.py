"""Repositories of the analysis: operators, snapshots and runs. All three are append-only
apart from the supersede mark on a snapshot."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import (
    add_row,
    dump,
    fetch,
    json_object,
    newest_first,
    oldest_first,
    require,
    rows,
)
from ada.adapters.db.tables import (
    DataSourceRow,
    OperatorInputRow,
    OperatorRow,
    RunRow,
    RunSnapshotRow,
    SnapshotRow,
)
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.operators import Operator, OperatorId, OperatorKind
from ada.core.models.runs import Run, Snapshot
from ada.core.models.schema import Schema
from ada.core.models.time import Interval, TimeRange
from ada.core.ports.repositories import OperatorRepository, RunRepository, SnapshotRepository


def _operator(row: OperatorRow) -> Operator:
    return Operator(
        id=row.id,
        project_id=row.project_id,
        kind=OperatorKind(row.kind),
        params=row.params,
        inputs=tuple(row.inputs),
        output=Schema.model_validate(row.output),
        materializing=row.materializing,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )


def _data_source_id(operator: Operator) -> UUID | None:
    """The data source a source operator reads, in the column that finds it again."""
    if operator.kind is not OperatorKind.SOURCE:
        return None
    value = operator.params.get("data_source_id")
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        raise Invalid(f"data_source_id {value!r} of a source operator is not an id") from None


class SqlOperatorRepository(OperatorRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: OperatorId) -> Operator:
        return _operator(await fetch(self.session, OperatorRow, id, "operator"))

    async def add(self, operator: Operator) -> Operator:
        data_source_id = _data_source_id(operator)
        if data_source_id is not None:
            await require(self.session, DataSourceRow, data_source_id, "data source")
        found = await self.session.scalars(
            select(OperatorRow.id).where(OperatorRow.id.in_(operator.inputs))
        )
        for input_id in set(operator.inputs) - set(found.all()):
            raise NotFound("operator", input_id)

        # The same definition is the same operator, so a second add (or a concurrent one)
        # keeps whatever was stored first.
        inserted = await self.session.scalar(
            insert(OperatorRow)
            .values(
                id=operator.id,
                project_id=operator.project_id,
                kind=operator.kind.value,
                params=json_object(operator.params),
                inputs=list(operator.inputs),
                output=dump(operator.output),
                materializing=operator.materializing,
                data_source_id=data_source_id,
                created_by=dump(operator.created_by),
                created_at=operator.created_at,
            )
            .on_conflict_do_nothing(index_elements=[OperatorRow.id])
            .returning(OperatorRow.id)
        )
        if inserted is None:
            return await self.get(operator.id)
        if operator.inputs:
            await self.session.execute(
                insert(OperatorInputRow).values(
                    [
                        {"operator_id": operator.id, "position": position, "input_id": input_id}
                        for position, input_id in enumerate(operator.inputs)
                    ]
                )
            )
        # What was stored is what get returns: the params went through JSON.
        return await self.get(operator.id)

    async def list(self, project_id: Id) -> Sequence[Operator]:
        statement = oldest_first(OperatorRow, OperatorRow.project_id == project_id)
        return [_operator(row) for row in await rows(self.session, statement)]

    async def upstream(self, id: OperatorId) -> Sequence[Operator]:
        # One recursive query finds the whole pipeline; the order is then worked out here,
        # because it follows each operator's inputs in their declared order.
        reached = select(cast(literal(id), String(64)).label("id")).cte("reached", recursive=True)
        reached = reached.union(
            select(OperatorInputRow.input_id).join(
                reached, OperatorInputRow.operator_id == reached.c.id
            )
        )
        found = await rows(
            self.session, select(OperatorRow).where(OperatorRow.id.in_(select(reached.c.id)))
        )
        operators = {row.id: _operator(row) for row in found}
        if id not in operators:
            raise NotFound("operator", id)

        # Depth first, inputs in order, each operator once, after everything it reads. An
        # explicit stack keeps long chains from hitting the recursion limit.
        ordered: list[Operator] = []
        visited = {id}
        stack = [(id, iter(operators[id].inputs))]
        while stack:
            current, inputs = stack[-1]
            for input_id in inputs:
                if input_id not in visited:
                    visited.add(input_id)
                    stack.append((input_id, iter(operators[input_id].inputs)))
                    break
            else:
                ordered.append(operators[current])
                stack.pop()
        return ordered

    async def reading(self, data_source_id: Id) -> Sequence[Operator]:
        statement = oldest_first(
            OperatorRow,
            OperatorRow.data_source_id == data_source_id,
            OperatorRow.kind == OperatorKind.SOURCE.value,
        )
        return [_operator(row) for row in await rows(self.session, statement)]


def _snapshot(row: SnapshotRow) -> Snapshot:
    period = None
    if row.period_start is not None and row.period_end is not None:
        period = Interval(start=row.period_start, end=row.period_end)
    return Snapshot(
        id=row.id,
        project_id=row.project_id,
        operator_id=row.operator_id,
        parameters_key=row.parameters_key,
        period=period,
        content_hash=row.content_hash,
        location=row.location,
        row_count=row.row_count,
        fetched_at=row.fetched_at,
        superseded_at=row.superseded_at,
    )


class SqlSnapshotRepository(SnapshotRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Snapshot:
        return _snapshot(await fetch(self.session, SnapshotRow, id, "snapshot"))

    async def add(self, snapshot: Snapshot) -> None:
        await require(self.session, OperatorRow, snapshot.operator_id, "operator")
        row = SnapshotRow(
            id=snapshot.id,
            project_id=snapshot.project_id,
            operator_id=snapshot.operator_id,
            parameters_key=snapshot.parameters_key,
            period_start=snapshot.period.start if snapshot.period else None,
            period_end=snapshot.period.end if snapshot.period else None,
            content_hash=snapshot.content_hash,
            location=snapshot.location,
            row_count=snapshot.row_count,
            fetched_at=snapshot.fetched_at,
            superseded_at=snapshot.superseded_at,
        )
        await add_row(self.session, row)

    async def current(self, operator_id: OperatorId, parameters_key: str) -> Snapshot | None:
        row = await self.session.scalar(
            select(SnapshotRow)
            .where(
                SnapshotRow.operator_id == operator_id,
                SnapshotRow.parameters_key == parameters_key,
                SnapshotRow.superseded_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        return _snapshot(row) if row is not None else None

    async def supersede(self, id: Id, at: datetime) -> None:
        table = SnapshotRow.__table__
        result = await self.session.execute(
            update(table).where(table.c.id == id).values(superseded_at=at)
        )
        if result.rowcount == 0:
            raise NotFound("snapshot", id)

    async def list(self, operator_id: OperatorId) -> Sequence[Snapshot]:
        statement = oldest_first(
            SnapshotRow, SnapshotRow.operator_id == operator_id, by=SnapshotRow.fetched_at
        )
        return [_snapshot(row) for row in await rows(self.session, statement)]


def _run(row: RunRow, snapshots: dict[OperatorId, Id]) -> Run:
    return Run(
        id=row.id,
        project_id=row.project_id,
        time_range=TimeRange(start=row.time_start, end=row.time_end),
        bindings=row.bindings,
        snapshots=snapshots,
        started_by=Actor.model_validate(row.started_by),
        started_at=row.started_at,
    )


class SqlRunRepository(RunRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _assemble(self, found: Sequence[RunRow]) -> list[Run]:
        """Runs with their `snapshots` filled in from run_snapshots, in one extra query."""
        fixed: dict[UUID, dict[OperatorId, Id]] = defaultdict(dict)
        if found:
            statement = select(RunSnapshotRow).where(
                RunSnapshotRow.run_id.in_([row.id for row in found])
            )
            for link in await rows(self.session, statement):
                fixed[link.run_id][link.operator_id] = link.snapshot_id
        return [_run(row, fixed[row.id]) for row in found]

    async def get(self, id: Id) -> Run:
        row = await fetch(self.session, RunRow, id, "run")
        return (await self._assemble([row]))[0]

    async def add(self, run: Run) -> None:
        for snapshot_id in run.snapshots.values():
            await require(self.session, SnapshotRow, snapshot_id, "snapshot")
        for operator_id in run.snapshots:
            await require(self.session, OperatorRow, operator_id, "operator")
        await add_row(
            self.session,
            RunRow(
                id=run.id,
                project_id=run.project_id,
                time_start=run.time_range.start,
                time_end=run.time_range.end,
                bindings=json_object(run.bindings),
                started_by=dump(run.started_by),
                started_at=run.started_at,
            ),
        )
        for operator_id, snapshot_id in run.snapshots.items():
            self.session.add(
                RunSnapshotRow(run_id=run.id, operator_id=operator_id, snapshot_id=snapshot_id)
            )
        await self.session.flush()

    async def list(self, project_id: Id, limit: int = 50) -> Sequence[Run]:
        statement = newest_first(RunRow, RunRow.started_at, RunRow.project_id == project_id)
        return await self._assemble(await rows(self.session, statement.limit(limit)))

    async def fix_snapshot(self, run_id: Id, operator_id: OperatorId, snapshot_id: Id) -> Run:
        run = await self.get(run_id)
        if operator_id in run.snapshots:
            return run
        await require(self.session, OperatorRow, operator_id, "operator")
        await require(self.session, SnapshotRow, snapshot_id, "snapshot")
        # Two writers racing for the same operator: the first insert wins, the other adds
        # nothing, and both read back the same run.
        await self.session.execute(
            insert(RunSnapshotRow)
            .values(run_id=run_id, operator_id=operator_id, snapshot_id=snapshot_id)
            .on_conflict_do_nothing(index_elements=["run_id", "operator_id"])
        )
        return await self.get(run_id)
