from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.analysis import Rows
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.operators import (
    InputParams,
    Operator,
    OperatorId,
    OperatorKind,
    SourceParams,
    TransformParams,
)
from ada.core.models.runs import Run, Snapshot
from ada.core.models.time import TimeRange
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import OperatorRepository, RunRepository, SnapshotRepository
from ada.core.ports.system import Clock
from ada.core.services.pipelines.fusion import (
    Node,
    PeriodFilterNode,
    QueryNode,
    SnapshotNode,
    compose,
)
from ada.core.services.pipelines.fusion import parameters_key as key_of
from ada.core.services.pipelines.schemas import (
    SOURCE_KEY,
    Columns,
    check_fits,
    check_still_matches,
)
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService
from ada.core.services.schema.roles import check_compatible
from ada.core.services.schema.time import check_range, is_bounded


class _NeedsExecution(Exception):
    """Planning without fixing met a materializing operator the run has not fixed yet."""


class Runs(RunService):
    """Plans and executes runs.

    Planning walks upstream from the requested operator. Materializing operators are
    pipeline breakers: each resolves to one stored snapshot, reused when one exists for
    its identity and parameters, created otherwise, and fixed in the run either way, so
    every later read through the run sees the same state. Pass-through operators store
    nothing; a chain of them becomes one query over the snapshots below it (fusion.py).
    Input operators stand for whatever the run binds to their name, or their default.
    """

    def __init__(
        self,
        runs: RunRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        sources: SourceService,
        store: AnalysisStore,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.runs = runs
        self.operators = operators
        self.snapshots = snapshots
        self.sources = sources
        self.store = store
        self.events = events
        self.clock = clock
        self.columns = Columns(operators, snapshots, sources, store)

    async def start(
        self,
        project_id: Id,
        actor: Actor,
        time_range: TimeRange | None = None,
        bindings: dict[str, OperatorId] | None = None,
    ) -> Run:
        bindings = bindings or {}
        try:
            check_range(time_range or TimeRange())
        except ValueError as error:
            raise Invalid(str(error)) from None
        if bindings:
            await self._check_bindings(project_id, bindings)
        run = Run(
            id=uuid7(),
            project_id=project_id,
            time_range=time_range or TimeRange(),
            bindings=bindings,
            started_by=actor,
            started_at=self.clock.now(),
        )
        await self.runs.add(run)
        return run

    async def get(self, id: Id) -> Run:
        return await self.runs.get(id)

    async def list(self, project_id: Id, limit: int = 50) -> Sequence[Run]:
        return await self.runs.list(project_id, limit)

    async def snapshot(self, id: Id) -> Snapshot:
        return await self.snapshots.get(id)

    async def execute(self, run_id: Id, operator_id: OperatorId) -> Run:
        run, _ = await self._execute(run_id, operator_id)
        return run

    async def read(self, run_id: Id, operator_id: OperatorId, limit: int = 1000) -> Rows:
        run = await self.runs.get(run_id)
        operator = await self._operator(run, operator_id)
        try:
            # Everything below is fixed already: answer without executing, and without
            # announcing a run that did nothing. Widgets read often.
            node = await _Planner(self, run, fix=False).node(operator.id)
        except _NeedsExecution:
            run, node = await self._execute(run_id, operator_id)
        return await self.store.run(compose(node), limit)

    async def _execute(self, run_id: Id, operator_id: OperatorId) -> tuple[Run, Node]:
        run = await self.runs.get(run_id)
        operator = await self._operator(run, operator_id)
        await self._publish(EventType.RUN_STARTED, run, operator_id)
        try:
            planner = _Planner(self, run, fix=True)
            node = await planner.node(operator.id)
            if isinstance(node, QueryNode):
                # Validate the declaration against what the query really returns now.
                actual = await self.store.describe(compose(node))
                check_still_matches(operator.output.columns, actual, f"Operator {operator.id}")
        except Exception as error:
            await self._publish(EventType.RUN_FAILED, run, operator_id, error=str(error))
            raise
        await self._publish(EventType.RUN_FINISHED, planner.run, operator_id)
        return planner.run, node

    async def _check_bindings(self, project_id: Id, bindings: dict[str, OperatorId]) -> None:
        slots: dict[str, list[Operator]] = {}
        for operator in await self.operators.list(project_id):
            if operator.kind is OperatorKind.INPUT:
                name = InputParams.model_validate(operator.params).name
                slots.setdefault(name, []).append(operator)
        for name, bound_id in bindings.items():
            if name not in slots:
                raise Invalid(f"The project has no input named {name!r}")
            try:
                bound = await self.operators.get(bound_id)
            except NotFound:
                raise Invalid(f"Operator {bound_id}, bound to {name!r}, does not exist") from None
            if bound.project_id != project_id:
                raise Invalid(f"Operator {bound_id} belongs to another project")
            upstream = {operator.id for operator in await self.operators.upstream(bound_id)}
            if any(slot.id in upstream for slot in slots[name]):
                raise Invalid(f"Operator {bound_id} reads the input {name!r} it is bound to")
            columns = await self.columns.of(bound)
            for slot in slots[name]:
                check_fits(slot.output, columns, f"The binding of {name!r}")
                check_compatible(slot.output.roles, bound.output.roles, f"The binding of {name!r}")

    async def _operator(self, run: Run, operator_id: OperatorId) -> Operator:
        operator = await self.operators.get(operator_id)
        if operator.project_id != run.project_id:
            raise Invalid(f"Operator {operator_id} is not in the run's project")
        return operator

    async def _publish(
        self, type: EventType, run: Run, operator_id: OperatorId, error: str | None = None
    ) -> None:
        payload: dict[str, str] = {"run_id": str(run.id), "operator_id": operator_id}
        if error is not None:
            payload["error"] = error
        await self.events.publish(
            Event(type=type, project_id=run.project_id, payload=payload, at=self.clock.now())
        )


class _Planner:
    """One walk over a pipeline for one run. Holds the run as it gains fixed snapshots, and
    one node per operator, so a shared upstream is planned once and fused once."""

    def __init__(self, runs: Runs, run: Run, fix: bool) -> None:
        self.runs = runs
        self.run = run
        self.fix = fix
        self.nodes: dict[OperatorId, Node] = {}
        self.visiting: set[OperatorId] = set()

    async def node(self, operator_id: OperatorId) -> Node:
        if operator_id in self.nodes:
            return self.nodes[operator_id]
        if operator_id in self.visiting:
            raise Invalid(f"Operator {operator_id} depends on itself through an input binding")
        self.visiting.add(operator_id)
        operator = await self.runs._operator(self.run, operator_id)
        node = await self._plan(operator)
        if operator.kind is OperatorKind.SOURCE:
            node = self._in_range(operator, node)
        self.visiting.discard(operator_id)
        self.nodes[operator_id] = node
        return node

    async def _plan(self, operator: Operator) -> Node:
        if operator.id in self.run.snapshots:
            # Fixed earlier in this run: the run is a consistent cut, even if a newer
            # snapshot has appeared since.
            return SnapshotNode(await self.runs.snapshots.get(self.run.snapshots[operator.id]))
        match operator.kind:
            case OperatorKind.SOURCE:
                return SnapshotNode(await self._fix(operator, await self._source(operator)))
            case OperatorKind.INPUT:
                return await self.node(self._bound(operator))
            case OperatorKind.TRANSFORM:
                if operator.materializing:
                    self._require_fixing()
                sql = TransformParams.model_validate(operator.params).sql
                inputs = tuple([await self.node(input_id) for input_id in operator.inputs])
                query = QueryNode(operator.id, sql, inputs)
                if not operator.materializing:
                    return query
                snapshot = await self._materialize(operator, query)
                return SnapshotNode(await self._fix(operator, snapshot))
            case kind:
                raise Invalid(f"{kind.value.capitalize()} operators cannot run yet")

    def _in_range(self, operator: Operator, node: Node) -> Node:
        """A source's rows in the run's time range. Sources that fetched only the
        requested periods are already in it, and filtering them again changes nothing; a
        source read whole is filtered here. A source without a time role ignores the
        range, and so does everything downstream of it."""
        time = operator.output.roles.time
        if time is None or not is_bounded(self.run.time_range):
            return node
        return PeriodFilterNode(node, time, self.run.time_range)

    def _bound(self, operator: Operator) -> OperatorId:
        name = InputParams.model_validate(operator.params).name
        if name in self.run.bindings:
            return self.run.bindings[name]
        if not operator.inputs:
            raise Invalid(f"The input {name!r} has no default and the run binds nothing to it")
        return operator.inputs[0]

    async def _source(self, operator: Operator) -> Snapshot:
        self._require_fixing()
        runs = self.runs
        data_source_id = SourceParams.model_validate(operator.params).data_source_id
        if is_bounded(self.run.time_range):
            # Pushdown: only the requested periods, fetched where missing or stale. A
            # source that cannot fetch by period answers None and is read whole below.
            ranged = await runs.sources.refresh_range(data_source_id, self.run.time_range)
            if ranged is not None:
                return ranged
        try:
            # The source service decides by its freshness policy whether to fetch; most
            # calls change nothing.
            await runs.sources.refresh(data_source_id)
        except Exception:
            # A failed refresh keeps the last good snapshot current; without one there is
            # nothing to serve, and the failure is the answer.
            if await runs.snapshots.current(operator.id, SOURCE_KEY) is None:
                raise
        snapshot = await runs.snapshots.current(operator.id, SOURCE_KEY)
        if snapshot is None:
            raise Invalid(f"The source of operator {operator.id} has no data yet")
        return snapshot

    async def _materialize(self, operator: Operator, query: QueryNode) -> Snapshot:
        runs = self.runs
        key = key_of(query.inputs)
        current = await runs.snapshots.current(query.operator_id, key)
        if current is not None:
            return current
        stored = await runs.store.materialize(self.run.project_id, compose(query))
        check_still_matches(
            operator.output.columns, stored.output.columns, f"Operator {operator.id}"
        )
        snapshot = Snapshot(
            id=uuid7(),
            project_id=self.run.project_id,
            operator_id=query.operator_id,
            parameters_key=key,
            content_hash=stored.content_hash,
            location=stored.location,
            row_count=stored.row_count,
            fetched_at=runs.clock.now(),
        )
        await runs.snapshots.add(snapshot)
        return snapshot

    async def _fix(self, operator: Operator, snapshot: Snapshot) -> Snapshot:
        self.run = await self.runs.runs.fix_snapshot(self.run.id, operator.id, snapshot.id)
        # Another request may have fixed a different snapshot first; the run keeps that one.
        if self.run.snapshots[operator.id] != snapshot.id:
            return await self.runs.snapshots.get(self.run.snapshots[operator.id])
        return snapshot

    def _require_fixing(self) -> None:
        if not self.fix:
            raise _NeedsExecution
