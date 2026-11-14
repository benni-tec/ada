"""PipelineService and RunService over real DuckDB in tmp_path, the memory repositories and
a small fake of the source service that writes snapshots the way the real one does."""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid7

import pytest

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryRunRepository,
    MemorySnapshotRepository,
    MemoryStore,
)
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.analysis import FetchedData, Query, StoredSnapshot
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.events import EventType
from ada.core.models.operators import Operator, OperatorKind, operator_identity
from ada.core.models.runs import Snapshot
from ada.core.models.schema import (
    Column,
    ColumnType,
    MeasureRole,
    Roles,
    Schema,
)
from ada.core.models.sources import AccessKind, DataFormat, DataSource, FreshnessPolicy
from ada.core.models.sources import RefreshResult as Refreshed
from ada.core.services.pipelines.fusion import StandInNode, compose
from ada.core.services.pipelines.runs import Runs
from ada.core.services.pipelines.service import Pipelines
from ada.core.services.ports.sources import SourceService
from factories import AGENT, data_source
from fakes import FixedClock

pytestmark = pytest.mark.anyio

SYSTEM = Actor(kind=ActorKind.SYSTEM, name="ada")
REGIONS = b"region,value\nHelsinki,10\nTurku,20\nOulu,30\n"
DECLARED = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="value", type=ColumnType.INTEGER),
    )
)


class RecordingStore(DuckDbAnalysisStore):
    """The real store, remembering what it was asked to run and materialize."""

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)
        self.queries: list[Query] = []
        self.materialized: list[Query] = []
        self.described: list[Query] = []

    async def run(self, query: Query, limit: int):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        return await super().run(query, limit)

    async def materialize(self, project_id: Id, query: Query) -> StoredSnapshot:
        self.materialized.append(query)
        return await super().materialize(project_id, query)

    async def describe(self, query: Query) -> tuple[Column, ...]:
        self.described.append(query)
        return await super().describe(query)


class FakeSources(SourceService):
    """Registers sources and refreshes them as the source service is agreed to: the source
    operator is added at registration, and a refresh writes a snapshot under it with an
    empty parameters key only when the content changed, superseding the old one."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.content: dict[Id, bytes] = {}
        self.refreshes: list[Id] = []
        self.failure: Exception | None = None

    async def add(
        self, project_id: Id, content: bytes, declared: Schema | None = None
    ) -> tuple[DataSource, Operator]:
        source = data_source(project_id, declared_schema=declared)
        await self.world.data_sources.add(source)
        self.content[source.id] = content
        params: JsonObject = {"data_source_id": str(source.id)}
        operator = Operator(
            id=operator_identity(project_id, OperatorKind.SOURCE, params, ()),
            project_id=project_id,
            kind=OperatorKind.SOURCE,
            params=params,
            output=declared or Schema(),
            materializing=True,
            created_by=SYSTEM,
            created_at=self.world.clock.now(),
        )
        return source, await self.world.operators.add(operator)

    async def refresh(self, id: Id, force: bool = False) -> Refreshed:
        self.refreshes.append(id)
        if self.failure:
            raise self.failure
        world = self.world
        source = await world.data_sources.get(id)
        data = FetchedData(
            content=self.content[id],
            format=DataFormat.CSV,
            fetched_at=world.clock.now(),
            origin=source.address,
        )
        stored = await world.store.write(source.project_id, data, source.declared_schema)
        (operator,) = await world.operators.reading(id)
        current = await world.snapshots.current(operator.id, "")
        if current and current.content_hash == stored.content_hash:
            return Refreshed(data_source_id=id, changed=False)
        snapshot = Snapshot(
            id=uuid7(),
            project_id=source.project_id,
            operator_id=operator.id,
            parameters_key="",
            content_hash=stored.content_hash,
            location=stored.location,
            row_count=stored.row_count,
            fetched_at=world.clock.now(),
        )
        await world.snapshots.add(snapshot)
        if current:
            await world.snapshots.supersede(current.id, world.clock.now())
        return Refreshed(data_source_id=id, changed=True, snapshot_ids=(snapshot.id,))

    async def register(  # type: ignore[override]
        self,
        project_id: Id,
        name: str,
        access_kind: AccessKind,
        address: str,
        format: DataFormat,
        options: JsonObject | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        raise NotImplementedError

    async def get(self, id: Id) -> DataSource:
        return await self.world.data_sources.get(id)

    async def list(self, project_id: Id) -> Sequence[DataSource]:
        return await self.world.data_sources.list(project_id)

    async def update(self, id: Id, expected_revision: int, **changes: object) -> DataSource:  # type: ignore[override]
        raise NotImplementedError

    async def due(self) -> Sequence[DataSource]:
        return []


class World:
    def __init__(self, tmp_path: Path) -> None:
        memory = MemoryStore()
        self.project_id = uuid7()
        self.clock = FixedClock()
        self.store = RecordingStore(tmp_path / "data")
        self.data_sources = MemoryDataSourceRepository(memory)
        self.operators = MemoryOperatorRepository(memory)
        self.snapshots = MemorySnapshotRepository(memory)
        self.runs_repository = MemoryRunRepository(memory)
        self.events = MemoryEventBus()
        self.sources = FakeSources(self)
        self.pipelines = Pipelines(
            self.operators, self.data_sources, self.snapshots, self.sources, self.store, self.clock
        )
        self.runs = Runs(
            self.runs_repository,
            self.operators,
            self.snapshots,
            self.sources,
            self.store,
            self.events,
            self.clock,
        )

    async def source(
        self, content: bytes = REGIONS, declared: Schema | None = DECLARED
    ) -> Operator:
        _, operator = await self.sources.add(self.project_id, content, declared)
        return operator

    async def transform(self, sql: str, *inputs: Operator, **options: object) -> Operator:
        return await self.pipelines.add_transform(
            self.project_id, sql, [i.id for i in inputs], AGENT, **options
        )

    async def read(self, operator: Operator, run_id: Id | None = None) -> list[tuple[object, ...]]:
        run_id = run_id or (await self.runs.start(self.project_id, AGENT)).id
        return list((await self.runs.read(run_id, operator.id)).rows)

    def set_content(self, operator: Operator, content: bytes) -> None:
        self.sources.content[UUID(operator.params["data_source_id"])] = content


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


# Building pipelines


async def test_add_source_returns_the_operator_registration_added(world: World) -> None:
    source, registered = await world.sources.add(world.project_id, REGIONS, DECLARED)

    operator = await world.pipelines.add_source(world.project_id, source.id, AGENT)

    assert operator == registered
    assert operator.created_by == SYSTEM


async def test_add_source_adds_the_agreed_definition_when_missing(world: World) -> None:
    source = data_source(world.project_id, declared_schema=DECLARED)
    await world.data_sources.add(source)

    operator = await world.pipelines.add_source(world.project_id, source.id, AGENT)

    params = {"data_source_id": str(source.id)}
    assert operator.id == operator_identity(world.project_id, OperatorKind.SOURCE, params, ())
    assert (operator.params, operator.inputs, operator.materializing) == (params, (), True)
    assert operator.output == DECLARED
    assert await world.pipelines.add_source(world.project_id, source.id, AGENT) == operator


async def test_add_source_refuses_a_source_of_another_project(world: World) -> None:
    source = data_source(uuid7())
    await world.data_sources.add(source)
    with pytest.raises(Invalid):
        await world.pipelines.add_source(world.project_id, source.id, AGENT)


async def test_a_transform_derives_its_columns_from_declared_inputs_without_data(
    world: World,
) -> None:
    source = await world.source()

    total = await world.transform(
        "SELECT count(*) AS n, sum(value) / 2 AS half, region || '!' AS shout FROM input_0 "
        "GROUP BY region;",
        source,
    )

    assert total.output.columns == (
        Column(name="n", type=ColumnType.INTEGER),
        Column(name="half", type=ColumnType.NUMBER),
        Column(name="shout", type=ColumnType.TEXT),
    )
    assert total.output.derived is True
    assert total.materializing is False
    # The trailing semicolon is not part of the definition.
    assert total.params == {"sql": total.params["sql"].rstrip(";")}
    # The source's declared columns sufficed: nothing was fetched.
    assert world.sources.refreshes == []


async def test_a_transform_over_an_undeclared_source_describes_its_data(world: World) -> None:
    source = await world.source(declared=None)

    doubled = await world.transform("SELECT region, value * 2 AS twice FROM input_0", source)

    assert len(world.sources.refreshes) == 1
    assert doubled.output.columns == (
        Column(name="region", type=ColumnType.TEXT),
        Column(name="twice", type=ColumnType.INTEGER),
    )


async def test_adding_a_transform_twice_returns_the_stored_one(world: World) -> None:
    source = await world.source()
    first = await world.transform("SELECT region FROM input_0", source)
    described = len(world.store.described)

    again = await world.transform("SELECT region FROM input_0", source, materialize=True)

    assert again == first
    assert len(world.store.described) == described


@pytest.mark.parametrize(
    "sql",
    ["SELECT nope FROM input_0", "SELECT * FROM input_1", "SELEC 1", "SELECT 1; SELECT 2", ";"],
)
async def test_a_transform_with_bad_sql_is_invalid(world: World, sql: str) -> None:
    source = await world.source()
    with pytest.raises(Invalid):
        await world.transform(sql, source)
    assert await world.operators.list(world.project_id) == [source]


async def test_declared_roles_must_name_fitting_columns(world: World) -> None:
    source = await world.source()
    sql = "SELECT region, value, value > 15 AS hidden FROM input_0"

    with pytest.raises(Invalid, match="missing"):
        await world.transform(sql, source, roles=Roles(measures=(MeasureRole(value="missing"),)))
    with pytest.raises(Invalid, match="region"):
        await world.transform(sql, source, roles=Roles(measures=(MeasureRole(value="region"),)))
    with pytest.raises(Invalid, match="value"):
        roles = Roles(measures=(MeasureRole(value="value", suppressed="value"),))
        await world.transform(sql, source, roles=roles)

    roles = Roles(measures=(MeasureRole(value="value", suppressed="hidden"),))
    operator = await world.transform(sql, source, roles=roles)
    assert operator.output.roles == roles
    assert operator.output.derived is False


async def test_a_transform_over_a_missing_operator_is_invalid(world: World) -> None:
    with pytest.raises(Invalid):
        await world.pipelines.add_transform(world.project_id, "SELECT 1", ["op_nope"], AGENT)


async def test_an_input_checks_its_default_against_its_schema(world: World) -> None:
    source = await world.source()

    slot = await world.pipelines.add_input(world.project_id, "regions", DECLARED, source.id, AGENT)
    narrower = Schema(columns=(Column(name="value", type=ColumnType.NUMBER),))
    assert await world.pipelines.add_input(world.project_id, "values", narrower, source.id, AGENT)

    assert slot.inputs == (source.id,)
    assert slot.materializing is False
    wrong = Schema(columns=(Column(name="region", type=ColumnType.INTEGER),))
    with pytest.raises(Invalid, match="region"):
        await world.pipelines.add_input(world.project_id, "codes", wrong, source.id, AGENT)


async def test_lineage_lists_the_pipeline_inputs_first(world: World) -> None:
    source = await world.source()
    slot = await world.pipelines.add_input(world.project_id, "regions", DECLARED, source.id, AGENT)
    top = await world.transform("SELECT * FROM input_0", slot)

    assert [o.id for o in await world.pipelines.lineage(top.id)] == [source.id, slot.id, top.id]
    assert await world.pipelines.get(top.id) == top


# Running pipelines


async def test_a_chain_of_pass_through_transforms_is_one_query(world: World) -> None:
    source = await world.source()
    big = await world.transform("SELECT * FROM input_0 WHERE value > 10", source)
    named = await world.transform(
        "WITH x AS (SELECT * FROM input_0) SELECT upper(region) AS r, value FROM x", big
    )
    ordered = await world.transform("SELECT * FROM input_0 ORDER BY value DESC", named)

    assert await world.read(ordered) == [("OULU", 30), ("TURKU", 20)]

    # One query over the one source snapshot; nothing was stored but the source.
    (query,) = world.store.queries
    assert list(query.relations.values()) == [
        (await world.snapshots.current(source.id, "")).location  # type: ignore[union-attr]
    ]
    assert world.store.materialized == []
    for operator in (big, named, ordered):
        assert await world.snapshots.list(operator.id) == []


async def test_a_shared_upstream_is_fused_once(world: World) -> None:
    source = await world.source()
    left = await world.transform("SELECT region, value FROM input_0", source)
    right = await world.transform("SELECT region, value * 10 AS big FROM input_0", source)
    joined = await world.transform(
        "SELECT a.region, a.value, b.big FROM input_0 a JOIN input_1 b USING (region) "
        "ORDER BY a.region",
        left,
        right,
    )

    assert await world.read(joined) == [
        ("Helsinki", 10, 100),
        ("Oulu", 30, 300),
        ("Turku", 20, 200),
    ]
    assert len(world.store.queries[0].relations) == 1


async def test_a_materializing_transform_is_reused_while_its_inputs_are_unchanged(
    world: World,
) -> None:
    source = await world.source()
    total = await world.transform(
        "SELECT sum(value) AS total FROM input_0", source, materialize=True
    )
    on_top = await world.transform("SELECT total + 1 AS more FROM input_0", total)

    first = await world.runs.execute(
        (await world.runs.start(world.project_id, AGENT)).id, on_top.id
    )
    second = await world.runs.execute(
        (await world.runs.start(world.project_id, AGENT)).id, on_top.id
    )

    assert len(world.store.materialized) == 1
    assert first.snapshots == second.snapshots
    assert set(first.snapshots) == {source.id, total.id}
    assert await world.read(on_top) == [(61,)]
    # The pass-through operator on top stored nothing.
    assert await world.snapshots.list(on_top.id) == []


async def test_a_refetch_with_identical_content_reuses_downstream_snapshots(world: World) -> None:
    source = await world.source()
    total = await world.transform(
        "SELECT sum(value) AS total FROM input_0", source, materialize=True
    )
    await world.read(total)

    # The same table in another layout: the same content hash, so nothing reruns.
    world.set_content(source, b"region,value\nOulu,30\nTurku,20\nHelsinki,10\n")
    await world.read(total)

    assert len(world.store.materialized) == 1
    assert len(await world.snapshots.list(source.id)) == 1


async def test_new_source_data_makes_a_new_snapshot_and_old_runs_keep_theirs(
    world: World,
) -> None:
    source = await world.source()
    total = await world.transform(
        "SELECT sum(value) AS total FROM input_0", source, materialize=True
    )
    old_run = await world.runs.start(world.project_id, AGENT)
    assert await world.read(total, old_run.id) == [(60,)]

    world.set_content(source, b"region,value\nHelsinki,100\n")
    new_run = await world.runs.start(world.project_id, AGENT)
    assert await world.read(total, new_run.id) == [(100,)]

    # The old run is a consistent cut: same snapshots, same answer.
    assert await world.read(total, old_run.id) == [(60,)]
    assert await world.read(source, old_run.id) == [("Helsinki", 10), ("Turku", 20), ("Oulu", 30)]
    old = (await world.runs.get(old_run.id)).snapshots
    new = (await world.runs.get(new_run.id)).snapshots
    assert old[source.id] != new[source.id]
    assert old[total.id] != new[total.id]
    old_total = await world.snapshots.get(old[total.id])
    new_total = await world.snapshots.get(new[total.id])
    assert old_total.parameters_key != new_total.parameters_key
    assert old_total.superseded_at is None
    assert (await world.snapshots.get(old[source.id])).superseded_at is not None


async def test_a_run_refreshes_each_source_only_until_it_has_fixed_it(world: World) -> None:
    source = await world.source()
    run = await world.runs.start(world.project_id, AGENT)

    await world.read(source, run.id)
    await world.read(source, run.id)
    await world.runs.execute(run.id, source.id)

    assert len(world.sources.refreshes) == 1


async def test_a_failed_refresh_serves_the_last_good_snapshot(world: World) -> None:
    source = await world.source()
    await world.read(source)

    world.sources.failure = RuntimeError("the source is down")
    assert len(await world.read(source)) == 3

    fresh = await world.source(b"region,value\nVaasa,1\n")
    with pytest.raises(RuntimeError, match="down"):
        await world.read(fresh)


async def test_a_scenario_binds_an_input_to_another_pipeline(world: World) -> None:
    actual = await world.source()
    target = await world.source(b"region,value\nHelsinki,80\nTurku,80\nOulu,80\n")
    raised = await world.transform(
        "SELECT region, CASE WHEN region = 'Helsinki' THEN 80 ELSE value END AS value FROM input_0",
        actual,
    )
    slot = await world.pipelines.add_input(
        world.project_id, "screening", DECLARED, actual.id, AGENT
    )
    total = await world.transform("SELECT sum(value) AS total FROM input_0", slot, materialize=True)

    baseline = await world.runs.start(world.project_id, AGENT)
    goal = await world.runs.start(world.project_id, AGENT, bindings={"screening": target.id})
    helsinki = await world.runs.start(world.project_id, AGENT, bindings={"screening": raised.id})

    assert not baseline.is_scenario
    assert goal.is_scenario
    assert await world.read(total, baseline.id) == [(60,)]
    assert await world.read(total, goal.id) == [(240,)]
    assert await world.read(total, helsinki.id) == [(130,)]
    # The same operator, one snapshot per set of inputs it saw.
    assert len(await world.snapshots.list(total.id)) == 3


async def test_bindings_are_checked_when_the_run_starts(world: World) -> None:
    source = await world.source()
    slot = await world.pipelines.add_input(
        world.project_id, "screening", DECLARED, source.id, AGENT
    )
    other = await world.transform("SELECT region FROM input_0", source)
    reading_itself = await world.transform("SELECT * FROM input_0", slot)

    with pytest.raises(Invalid, match="no input named"):
        await world.runs.start(world.project_id, AGENT, bindings={"nothing": source.id})
    with pytest.raises(Invalid, match="'value' is missing"):
        await world.runs.start(world.project_id, AGENT, bindings={"screening": other.id})
    with pytest.raises(Invalid, match="does not exist"):
        await world.runs.start(world.project_id, AGENT, bindings={"screening": "op_nope"})
    with pytest.raises(Invalid, match="reads the input"):
        await world.runs.start(world.project_id, AGENT, bindings={"screening": reading_itself.id})
    assert await world.runs.list(world.project_id) == []


async def test_execute_publishes_started_and_finished(world: World) -> None:
    source = await world.source()
    run = await world.runs.start(world.project_id, AGENT)

    executed = await world.runs.execute(run.id, source.id)

    assert [(e.type, e.payload) for e in world.events.published] == [
        (EventType.RUN_STARTED, {"run_id": str(run.id), "operator_id": source.id}),
        (EventType.RUN_FINISHED, {"run_id": str(run.id), "operator_id": source.id}),
    ]
    assert all(e.project_id == world.project_id for e in world.events.published)
    assert await world.runs.get(run.id) == executed
    assert await world.runs.list(world.project_id) == [executed]


async def test_reading_a_fixed_run_publishes_nothing(world: World) -> None:
    source = await world.source()
    run = await world.runs.start(world.project_id, AGENT)
    await world.read(source, run.id)
    published = len(world.events.published)

    await world.read(source, run.id)

    assert published == 2
    assert len(world.events.published) == published


async def test_a_failing_execution_publishes_failed_with_the_error(world: World) -> None:
    source = await world.source(b"region,value\nHelsinki,x\n", declared=None)
    broken = await world.transform(
        "SELECT CAST(value AS INTEGER) AS n FROM input_0", source, materialize=True
    )
    run = await world.runs.start(world.project_id, AGENT)

    with pytest.raises(Invalid):
        await world.runs.execute(run.id, broken.id)

    started, failed = world.events.published
    assert started.type is EventType.RUN_STARTED
    assert failed.type is EventType.RUN_FAILED
    assert failed.payload["operator_id"] == broken.id
    assert "x" in failed.payload["error"]


async def test_a_run_fails_when_the_data_lost_a_declared_column(world: World) -> None:
    source = await world.source(declared=None)
    values = await world.transform("SELECT value FROM input_0", source)
    world.set_content(source, b"region,amount\nHelsinki,1\n")

    with pytest.raises(Invalid):
        await world.read(values)
    assert world.events.published[-1].type is EventType.RUN_FAILED


async def test_operators_of_another_project_cannot_run(world: World) -> None:
    source = await world.source()
    run = await world.runs.start(uuid7(), AGENT)
    with pytest.raises(Invalid):
        await world.runs.execute(run.id, source.id)


async def test_stand_ins_describe_back_to_the_types_they_stand_for(world: World) -> None:
    columns = tuple(Column(name=f"a {t.value}", type=t) for t in ColumnType)

    described = await world.store.describe(compose(StandInNode(columns)))

    assert described == columns
