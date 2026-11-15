"""Pipelines: building and running them over real DuckDB in tmp_path and the memory
repositories, the DuckDB store itself, the pipelines list, and the roles checked before
anything runs (geography, periods, bounds, what a widget needs)."""

import re
from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import httpx
import pytest
from dishka import AsyncContainer
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

import factories
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryRunRepository,
    MemorySnapshotRepository,
    MemoryStore,
)
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.sources.examples import (
    SOTKANET_BREAST_SCREENING,
    SOTKANET_REGIONS,
    WELLBEING_COUNTY_BOUNDARIES,
)
from ada.composition import create_container
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
    GeoRole,
    MeasureRole,
    Roles,
    Schema,
    TimeRole,
)
from ada.core.models.sources import AccessKind, DataFormat, DataSource, FreshnessPolicy
from ada.core.models.sources import RefreshResult as Refreshed
from ada.core.models.time import Grain
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.pipelines.exploration import Exploration
from ada.core.services.pipelines.listing import sql_name
from ada.core.services.pipelines.runs import Runs
from ada.core.services.pipelines.service import Pipelines
from ada.core.services.ports.exploration import Clauses
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.core.services.schema import geo
from ada.core.services.schema.roles import check_compatible, check_widget
from ada.core.services.widgets import text
from ada.entrypoints.mcp.server import create_mcp
from api_support import call
from conftest import settings_in
from factories import AGENT, data_source
from fakes import FixedClock
from memory import MemoryBackground
from time_world import World as TimeWorld

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


# Building and running pipelines


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


async def test_adding_a_transform_twice_returns_the_stored_one(world: World) -> None:
    source = await world.source()
    first = await world.transform("SELECT region FROM input_0", source)
    described = len(world.store.described)

    again = await world.transform("SELECT region FROM input_0", source, materialize=True)

    assert again == first
    assert len(world.store.described) == described


@pytest.mark.parametrize(
    "sql",
    ["SELECT nope FROM input_0", "SELECT * FROM input_1", "SELECT 1; SELECT 2"],
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


# Exploring an operator with one query


async def test_a_query_puts_its_clauses_together_and_runs_only_one_select(world: World) -> None:
    source = await world.source()
    exploration = Exploration(world.operators, world.snapshots, world.runs, world.store)
    clauses = Clauses(
        select="value > 15 AS big, count(*) AS n, sum(value) AS total",
        where="region <> 'Nowhere'",
        group_by="GROUP BY big",
        having="count(*) > 0",
        order_by="big",
    )

    explored = await exploration.query(source.id, clauses, AGENT, limit=1)
    run = await world.runs.get(explored.run_id)  # type: ignore[arg-type]
    at_snapshot = await exploration.query(
        source.id,
        Clauses(select="sum(value) AS total"),
        AGENT,
        snapshot_id=run.snapshots[source.id],
    )

    assert [column.name for column in explored.rows.columns] == ["big", "n", "total"]
    assert (explored.rows.rows, explored.rows.truncated) == (((False, 1, 10),), True)
    assert (at_snapshot.rows.rows, at_snapshot.run_id) == (((60,),), None)
    for fragments in (
        {"select": "1; DROP TABLE input_0"},
        {"select": "*", "where": "true; COPY input_0 TO 'out.csv'"},
        {"select": " "},
    ):
        with pytest.raises(Invalid):
            await exploration.query(source.id, Clauses(**fragments), AGENT)
    with pytest.raises(Invalid):
        await exploration.query(source.id, Clauses(select="*"), AGENT, limit=501)
    # Nothing was stored for any of it.
    assert world.store.materialized == []
    assert await world.operators.list(world.project_id) == [source]


# The DuckDB store, against real Parquet files


PROJECT = uuid7()
CSV = b"region,value,day\nHelsinki,1.5,2024-01-01\nTurku,2,2024-02-01\n"


@pytest.fixture
def duckdb_store(tmp_path: Path) -> DuckDbAnalysisStore:
    return DuckDbAnalysisStore(tmp_path / "data")


def fetched(content: bytes, format: DataFormat = DataFormat.CSV) -> FetchedData:
    return FetchedData(content=content, format=format, fetched_at=factories.NOW, origin="test")


def snapshot_files(store: DuckDbAnalysisStore) -> list[str]:
    directory = store.data_dir / str(PROJECT)
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


def over(location: str, sql: str = "SELECT * FROM s") -> Query:
    return Query(sql=sql, relations={"s": location})


async def test_a_csv_becomes_one_parquet_file_with_columns_read_from_the_data(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    stored = await duckdb_store.write(PROJECT, fetched(CSV))

    assert stored.location == f"{PROJECT}/{stored.content_hash}.parquet"
    assert (duckdb_store.data_dir / stored.location).is_file()
    assert snapshot_files(duckdb_store) == [f"{stored.content_hash}.parquet"]
    assert stored.row_count == 2
    assert stored.output == Schema(
        columns=(
            Column(name="region", type=ColumnType.TEXT),
            Column(name="value", type=ColumnType.NUMBER),
            Column(name="day", type=ColumnType.DATE),
        ),
        derived=True,
    )
    rows = await duckdb_store.run(over(stored.location), limit=10)
    assert rows.rows == (("Helsinki", 1.5, date(2024, 1, 1)), ("Turku", 2.0, date(2024, 2, 1)))


async def test_identical_data_gets_the_same_hash_whatever_its_layout(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    first = await duckdb_store.write(PROJECT, fetched(CSV))
    again = await duckdb_store.write(PROJECT, fetched(CSV))
    # Quoted, with CRLF line ends and the rows the other way round: the same table.
    relaid = await duckdb_store.write(
        PROJECT,
        fetched(b'"region","value","day"\r\n"Turku",2,2024-02-01\r\n"Helsinki",1.5,2024-01-01\r\n'),
    )
    changed = await duckdb_store.write(PROJECT, fetched(CSV.replace(b"1.5", b"1.6")))

    assert first.content_hash == again.content_hash == relaid.content_hash
    assert first.location == again.location
    assert changed.content_hash != first.content_hash
    # One file per distinct content, and no scratch files left behind.
    assert snapshot_files(duckdb_store) == sorted(
        f"{h}.parquet" for h in {first.content_hash, changed.content_hash}
    )


async def test_a_declared_schema_adds_roles_to_the_columns_of_the_data(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    roles = Roles(
        geo=GeoRole(code="region", system="names", level="city"),
        measures=(MeasureRole(value="value"),),
    )
    declared = Schema(columns=(Column(name="value", type=ColumnType.NUMBER),), roles=roles)

    stored = await duckdb_store.write(PROJECT, fetched(CSV), declared)

    assert stored.output.roles == roles
    assert stored.output.derived is False
    # Columns still come from the data, all of them.
    assert [column.name for column in stored.output.columns] == ["region", "value", "day"]


async def test_describe_names_the_columns_without_running_the_query(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    stored = await duckdb_store.write(PROJECT, fetched(CSV))
    # Running this would take a very long time; describing only binds it.
    query = over(
        stored.location,
        "SELECT region, sum(value) AS total, count(*) AS n,"
        " (SELECT sum(x) FROM range(1000000000000) t(x)) AS huge FROM s GROUP BY region",
    )

    assert await duckdb_store.describe(query) == (
        Column(name="region", type=ColumnType.TEXT),
        Column(name="total", type=ColumnType.NUMBER),
        Column(name="n", type=ColumnType.INTEGER),
        Column(name="huge", type=ColumnType.INTEGER),
    )


async def test_run_returns_at_most_limit_rows_and_says_when_there_are_more(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    query = Query(sql="SELECT x, x * 1.5::DECIMAL(4, 1) AS y FROM range(5) t(x) ORDER BY x DESC")

    some = await duckdb_store.run(query, limit=2)
    every = await duckdb_store.run(query, limit=5)

    assert some.rows == ((4, 6.0), (3, 4.5))
    assert some.truncated is True
    assert len(every.rows) == 5
    assert every.truncated is False
    assert some.columns == (
        Column(name="x", type=ColumnType.INTEGER),
        Column(name="y", type=ColumnType.NUMBER),
    )


async def test_materialize_stores_the_query_result_as_a_snapshot(
    duckdb_store: DuckDbAnalysisStore,
) -> None:
    source = await duckdb_store.write(PROJECT, fetched(CSV))

    copy = await duckdb_store.materialize(PROJECT, over(source.location))
    total = await duckdb_store.materialize(
        PROJECT, over(source.location, "SELECT sum(value) AS t FROM s")
    )

    # The same table, by whatever route, is the same content.
    assert copy.content_hash == source.content_hash
    assert copy.location == source.location
    assert total.row_count == 1
    assert total.output.columns == (Column(name="t", type=ColumnType.NUMBER),)
    assert (await duckdb_store.run(over(total.location), 1)).rows == ((3.5,),)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('{other}')",
        "COPY (SELECT 1) TO '{other}'",
        "SET enable_external_access = true",
    ],
)
async def test_queries_cannot_reach_other_files(
    duckdb_store: DuckDbAnalysisStore, tmp_path: Path, sql: str
) -> None:
    other = tmp_path / "secret.csv"
    other.write_text("secret\n1\n")
    stored = await duckdb_store.write(PROJECT, fetched(CSV))
    query = over(stored.location, sql.format(other=other, data=duckdb_store.data_dir))

    with pytest.raises(Invalid):
        await duckdb_store.run(query, limit=10)
    with pytest.raises(Invalid):
        await duckdb_store.materialize(PROJECT, query)


@pytest.mark.parametrize("location", ["../outside.parquet", "/etc/passwd"])
async def test_relations_must_be_snapshots_in_the_data_directory(
    duckdb_store: DuckDbAnalysisStore, location: str
) -> None:
    with pytest.raises(Invalid):
        await duckdb_store.run(over(location), limit=1)


# The pipelines list


class Listing:
    """Operators stored directly, each a second later than the one before."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.project = factories.project()
        self.store.projects[self.project.id] = self.project
        self.ticks = 0

    def source(self, name: str) -> Operator:
        source = factories.data_source(self.project.id, name=name)
        self.store.data_sources[source.id] = source
        return self._add(OperatorKind.SOURCE, {"data_source_id": str(source.id)})

    def transform(self, sql: str, *inputs: Operator) -> Operator:
        return self._add(OperatorKind.TRANSFORM, {"sql": sql}, *inputs)

    def input(self, name: str, default: Operator) -> Operator:
        return self._add(OperatorKind.INPUT, {"name": name}, default)

    def _add(self, kind: OperatorKind, params: dict[str, Any], *inputs: Operator) -> Operator:
        self.ticks += 1
        operator = factories.operator(
            self.project.id,
            kind,
            params,
            inputs=tuple(i.id for i in inputs),
            created_at=factories.NOW + timedelta(seconds=self.ticks),
        )
        self.store.operators[operator.id] = operator
        return operator

    async def pipelines(self) -> Any:
        service = Pipelines(
            MemoryOperatorRepository(self.store),
            MemoryDataSourceRepository(self.store),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        return await service.pipelines(self.project.id)


async def test_only_operators_nothing_builds_on_are_pipelines_newest_first() -> None:
    world = Listing()
    screening = world.source("Sotkanet screening")
    regions = world.source("Regions")
    left = world.transform("-- Screening by county\nSELECT * FROM input_0", screening)
    right = world.transform("SELECT region, value FROM input_0 WHERE value > 1", screening)
    # A diamond: both sides read the screening source.
    joined = world.transform(
        "SELECT l.region, l.value, r.value AS previous FROM input_0 AS l "
        "JOIN input_1 AS r ON l.region = r.region",
        left,
        right,
    )
    baseline = world.input("baseline", regions)
    unused = world.source("Boundaries")

    pipelines = await world.pipelines()

    assert [p.operator_id for p in pipelines] == [unused.id, baseline.id, joined.id]
    by_id = {p.operator_id: p for p in pipelines}
    diamond = by_id[joined.id]
    assert [(str(s.data_source_id), s.name) for s in diamond.sources] == [
        (screening.params["data_source_id"], "Sotkanet screening")
    ]
    assert diamond.kind is OperatorKind.TRANSFORM
    assert diamond.name == "SELECT l.region, l.value, r.value AS previous FROM input_0…"
    assert diamond.output == joined.output
    assert diamond.created_at == joined.created_at
    assert by_id[baseline.id].name == "baseline"
    assert [s.name for s in by_id[baseline.id].sources] == ["Regions"]
    assert by_id[unused.id].name == "Boundaries"
    assert by_id[unused.id].kind is OperatorKind.SOURCE


def test_sql_is_named_by_its_leading_comment_or_its_first_words() -> None:
    assert sql_name("-- Participation by county\n-- (latest year)\nSELECT 1") == (
        "Participation by county (latest year)"
    )
    assert sql_name("  SELECT   region,\n  value FROM input_0  ") == (
        "SELECT region, value FROM input_0"
    )
    long = "SELECT " + ", ".join(f"column_{i}" for i in range(20)) + " FROM input_0"
    assert len(sql_name(long)) <= 60
    assert sql_name(long).endswith("…")


# Roles


COUNTY = GeoRole(code="region", system="statfin", level="wellbeing_services_county")
YEARS = TimeRole(start="period_start", end="period_end", grain=Grain.YEAR)
COLUMNS = (
    Column(name="region", type=ColumnType.TEXT),
    Column(name="period", type=ColumnType.TEXT),
    Column(name="value", type=ColumnType.NUMBER),
    Column(name="lower", type=ColumnType.NUMBER),
    Column(name="upper", type=ColumnType.NUMBER),
    Column(name="period_start", type=ColumnType.DATE),
    Column(name="period_end", type=ColumnType.DATE),
)
BOUNDED = MeasureRole(value="value", lower="lower", upper="upper")
TABLES = {
    "/years.csv": b"region,period,value,lower,upper\n01,2023,70,68,72\n01,2024,71,69,73\n"
    b"90,2023,74,72,76\n90,2024,74.3,72.1,76.5\n",
    "/quarters.csv": b"region,period,value,lower,upper\n01,2024Q1,70,68,72\n",
}


def schema(roles: Roles) -> Schema:
    return Schema(columns=COLUMNS, roles=roles)


class Tables(TimeWorld):
    """Small CSV sources answered in memory, each declared with the roles it is given."""

    def __init__(self, tmp_path: Path) -> None:
        def answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=TABLES[request.url.path])

        super().__init__(tmp_path, transport=httpx.MockTransport(answer))

    async def table(self, path: str, roles: Roles) -> Operator:
        source = await self.sources.register(
            self.project_id,
            name=path,
            access_kind=AccessKind.URL,
            address=f"https://tables.example{path}",
            format=DataFormat.CSV,
            options={"period": {"column": "period"}},
            declared_schema=schema(roles),
        )
        return await self.operator(source)


@pytest.fixture
def tables(tmp_path: Path) -> Tables:
    return Tables(tmp_path)


def test_a_binding_needs_the_slot_s_geography_and_period_shape() -> None:
    slot = Roles(time=YEARS, geo=COUNTY)
    check_compatible(slot, Roles(time=YEARS, geo=COUNTY, measures=(BOUNDED,)), "it")

    municipalities = COUNTY.model_copy(update={"level": "municipality"})
    with pytest.raises(Invalid, match="municipality in statfin codes"):
        check_compatible(slot, Roles(time=YEARS, geo=municipalities), "it")
    with pytest.raises(Invalid, match="by quarter"):
        check_compatible(
            slot, Roles(time=YEARS.model_copy(update={"grain": "quarter"}), geo=COUNTY), "it"
        )
    with pytest.raises(Invalid, match="no time role"):
        check_compatible(slot, Roles(geo=COUNTY), "it")
    with pytest.raises(Invalid, match="no geography role"):
        check_compatible(slot, Roles(time=YEARS), "it")
    # A slot without roles takes anything with the columns; a slot without a grain any
    # period shape.
    check_compatible(Roles(), Roles(), "it")
    check_compatible(Roles(time=YEARS.model_copy(update={"grain": None})), Roles(time=YEARS), "it")


async def test_a_run_refuses_a_binding_at_another_level_or_grain(tables: Tables) -> None:
    years = await tables.table("/years.csv", Roles(time=YEARS, geo=COUNTY))
    await tables.pipelines.add_input(
        tables.project_id, "screening", schema(Roles(time=YEARS, geo=COUNTY)), years.id, AGENT
    )
    quarters = await tables.table(
        "/quarters.csv",
        Roles(time=YEARS.model_copy(update={"grain": Grain.QUARTER}), geo=COUNTY),
    )
    unlabelled = await tables.transform("SELECT * FROM input_0", years)
    raised = await tables.transform(
        "SELECT * REPLACE (greatest(value, 80) AS value) FROM input_0",
        years,
        roles=Roles(time=YEARS, geo=COUNTY, measures=(MeasureRole(value="value"),)),
    )

    with pytest.raises(Invalid, match="its periods are by quarter, the slot's by year"):
        await tables.runs.start(tables.project_id, AGENT, bindings={"screening": quarters.id})
    with pytest.raises(Invalid, match="declares no time role"):
        await tables.runs.start(tables.project_id, AGENT, bindings={"screening": unlabelled.id})
    run = await tables.runs.start(tables.project_id, AGENT, bindings={"screening": raised.id})
    assert run.is_scenario


@pytest.mark.parametrize(
    ("type", "roles", "spec", "message"),
    [
        ("value", Roles(), {"column": "region"}, "needs a number, and 'region' is text"),
        ("map", Roles(geo=COUNTY.model_copy(update={"level": "mixed"})), {}, "mixed levels"),
        ("map", Roles(geo=COUNTY), {}, "boundaries in a column 'geometry'"),
        ("table", Roles(), {"labels": {"nope": "Nope"}}, "no column 'nope' for `labels`"),
        ("table", Roles(), {"format": {"value": "money"}}, "`format` of 'value' must be"),
        ("value", Roles(), {"compare_to": "region"}, "`compare_to` needs a number"),
        ("chart", Roles(), {"encoding": {}}, "a chart spec is a Vega-Lite spec with a `mark`"),
        (
            "chart",
            Roles(),
            {"mark": "bar", "data": {"values": [{"value": 1}]}},
            "`data` is not allowed: ADA puts the operator's rows in",
        ),
        (
            "chart",
            Roles(),
            {"layer": [{"mark": "image", "encoding": {"url": {"value": "https://x"}}}]},
            r"`layer\[0\]\.encoding\.url` is not allowed",
        ),
        (
            "chart",
            Roles(),
            {"mark": "bar", "encoding": {"href": {"field": "region"}}, "usermeta": {}},
            "`encoding.href` is not allowed.*`usermeta` is not allowed",
        ),
    ],
)
def test_a_widget_states_what_it_misses(
    type: str, roles: Roles, spec: dict[str, object], message: str
) -> None:
    with pytest.raises(Invalid, match=message):
        check_widget(type, schema(roles), spec)


def test_a_chart_table_and_value_take_their_options() -> None:
    target = {"mark": "rule", "encoding": {"y": {"datum": 80}}}
    line = {"mark": "line", "encoding": {"x": {"field": "period_start", "type": "temporal"}}}
    for type, spec in [
        ("chart", {"layer": [line, target], "config": {"axis": {"grid": False}}}),
        ("chart", {"facet": {"field": "region"}, "spec": line}),
        ("table", {"labels": {"value": "Coverage"}, "format": {"value": "percent"}, "decimals": 1}),
        ("value", {"compare_to": "lower", "format": "number"}),
        ("value", {"compare_to": 80}),
    ]:
        check_widget(type, schema(Roles()), spec)


# The text widget: placeholders, checked against every input


TEXT_INPUTS = {
    "main": Schema(
        columns=(
            Column(name="county", type=ColumnType.TEXT),
            Column(name="period_start", type=ColumnType.DATE),
            Column(name="period_end", type=ColumnType.DATE),
            Column(name="share", type=ColumnType.NUMBER),
        ),
        roles=Roles(time=TimeRole(start="period_start", end="period_end")),
    ),
    "gap": Schema(columns=(Column(name="gap", type=ColumnType.INTEGER),)),
}


def test_text_placeholders_parse_in_every_form_and_escape() -> None:
    segments, problems = text.parse(
        "# Gap\n{{gap.gap}} and {{ main.share:percent }} in "
        "{{main.share[county=North Karelia][period_end=2024-12-31]:signed1}};\n"
        "{{gap}} \\{{not.this}} {{oops"
    )

    found = [s for s in segments if isinstance(s, text.Placeholder)]
    assert [(p.input, p.column, p.filters, p.format, p.line) for p in found] == [
        ("gap", "gap", (), None, 2),
        ("main", "share", (), "percent", 2),
        (
            "main",
            "share",
            (("county", "North Karelia"), ("period_end", "2024-12-31")),
            "signed1",
            2,
        ),
        ("gap", None, (), None, 3),
    ]
    literal = "".join(s for s in segments if isinstance(s, str))
    assert "{{not.this}}" in literal and "\\" not in literal
    assert len(problems) == 1 and "line 3: `{{oops` is not a placeholder" in problems[0]


def test_a_text_widget_is_checked_against_its_inputs_and_names_every_problem() -> None:
    markdown = (
        "{{nope.share}} {{main.missing}} {{main.county:percent}} {{main.share[region=x]}} "
        "{{main.share:fancy}} <script>x</script> ![chart](https://x.test/a.png)"
    )

    with pytest.raises(Invalid) as refused:
        check_widget("text", TEXT_INPUTS["main"], {"markdown": markdown}, TEXT_INPUTS)

    message = str(refused.value)
    for problem in (
        "there is no input 'nope'; the widget has main, gap",
        "the input 'main' has no column 'missing'",
        "the format 'percent' needs a number, and 'county' is text",
        "has no column 'region' to filter on",
        'the format must be "integer", "number1", "percent", "plain" or "signed1"',
        "raw HTML is not allowed",
        "images are not allowed",
    ):
        assert problem in message, problem
    with pytest.raises(Invalid, match="holds only `markdown`"):
        check_widget("text", TEXT_INPUTS["main"], {"markdown": "x", "rows": [1]}, TEXT_INPUTS)
    with pytest.raises(Invalid, match="at most 20,000"):
        check_widget("text", TEXT_INPUTS["main"], {"markdown": "x" * 20_001}, TEXT_INPUTS)
    # An input no placeholder reads is only a warning; an autolink is a link, not HTML.
    assert check_widget(
        "text", TEXT_INPUTS["main"], {"markdown": "{{main.share}} <https://thl.fi>"}, TEXT_INPUTS
    ) == ["the input 'gap' is not used by any placeholder"]


def test_a_placeholder_shows_the_latest_period_or_the_only_row() -> None:
    main = text.InputRows(
        output=TEXT_INPUTS["main"],
        columns=TEXT_INPUTS["main"].columns,
        rows=(
            ("Kainuu", date(2023, 1, 1), date(2023, 12, 31), 61.25),
            ("Kainuu", date(2024, 1, 1), date(2024, 12, 31), 64.5),
            ("Lappi", date(2024, 1, 1), date(2024, 12, 31), 70.0),
        ),
    )
    gap = text.InputRows(
        output=TEXT_INPUTS["gap"], columns=TEXT_INPUTS["gap"].columns, rows=((1346,),)
    )
    many = text.InputRows(output=gap.output, columns=gap.columns, rows=((1,), (2,)))
    segments, _ = text.parse(
        "{{main.share[county=Kainuu]:percent}} {{main.share}} {{gap.gap}} "
        "{{main.share[county=Uusimaa]}} {{gap}}"
    )

    assert text.resolve(segments, {"main": main, "gap": gap}) == (
        "⟦main.share[county=Kainuu] = 64.5 %⟧ "
        "⟦main.share: no value, 2 rows remain in the latest period; pick one with "
        "[column=value]⟧ ⟦gap.gap = 1,346⟧ "
        "⟦main.share[county=Uusimaa]: no value, no row matches⟧ ⟦gap: the input's table, 1 rows⟧"
    )
    assert "2 rows remain and no time role" in text.resolve(
        text.parse("{{gap.gap}}")[0], {"gap": many}
    )


@pytest.mark.parametrize(
    ("cell", "column", "format", "shown"),
    [
        # The cases the widget bundle writes the same (services/widgets text/model.ts).
        (1234.567, "share", None, "1,235"),
        (12.345, "share", None, "12.35"),
        (12.0, "share", None, "12"),
        (13462, "cases", None, "13,462"),
        (2024, "year", None, "2024"),
        (12345.678, "share", "integer", "12,346"),
        (12345.678, "share", "number1", "12,345.7"),
        (72.0, "share", "number1", "72.0"),
        (72.46, "share", "percent", "72.5 %"),
        (72.0, "share", "percent", "72 %"),
        (12345.678, "share", "plain", "12345.678"),
        (1.25, "share", "signed1", "+1.3"),
        (-1.25, "share", "signed1", "\u22121.3"),
        (0.02, "share", "signed1", "\u00b10.0"),
        (-0.04, "share", "signed1", "\u00b10.0"),
        ("Kainuu", "county", None, "Kainuu"),
    ],
)
def test_a_placeholder_value_is_written_as_the_widget_writes_it(
    cell: object, column: str, format: str | None, shown: str
) -> None:
    kind = {str: ColumnType.TEXT, int: ColumnType.INTEGER}.get(type(cell), ColumnType.NUMBER)
    output = Schema(columns=(Column(name=column, type=kind),))

    assert text.formatted(cell, output.columns[0], format, output) == shown


async def test_create_widget_returns_invalid_with_the_reason(tables: Tables) -> None:
    years = await tables.table("/years.csv", Roles(time=YEARS, geo=COUNTY, measures=(BOUNDED,)))

    with pytest.raises(Invalid, match="A map widget cannot show this output: it needs the region"):
        await tables.widgets.create(tables.project_id, years.id, "map", "Screening", AGENT)
    widget = await tables.widgets.create(
        tables.project_id, years.id, "line-chart", "Screening", AGENT, spec={"series": "region"}
    )
    assert widget.type == "line-chart"
    assert tables.widget_repository.store.widgets == {widget.id: widget}


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        (
            "SELECT region, avg(value) AS value, min(lower) AS lower, max(upper) AS upper "
            "FROM input_0 GROUP BY region",
            "GROUP BY",
        ),
        (
            "SELECT * REPLACE (avg(value) OVER (PARTITION BY region) AS value) FROM input_0",
            "avg() OVER",
        ),
        (
            "SELECT s.* FROM (SELECT region, max(value) AS value, max(lower) AS lower, "
            "max(upper) AS upper FROM input_0 GROUP BY region) AS s JOIN input_0 USING (region)",
            "GROUP BY",
        ),
    ],
)
async def test_an_aggregating_transform_cannot_declare_bounds(
    tables: Tables, sql: str, reason: str
) -> None:
    years = await tables.table("/years.csv", Roles(measures=(BOUNDED,)))

    with pytest.raises(Invalid, match=re.escape(f"aggregates ({reason})")):
        await tables.transform(sql, years, roles=Roles(measures=(BOUNDED,)))
    # Without the bounds the same step is fine: the widget then draws no band.
    plain = await tables.transform(sql, years, roles=Roles(measures=(MeasureRole(value="value"),)))
    assert plain.output.roles.measures[0].lower is None


@pytest.mark.parametrize(
    "sql",
    [
        # A subquery that only picks the rows keeps them as they are: the latest period.
        "SELECT * FROM input_0 WHERE period_end = (SELECT max(period_end) FROM input_0)",
    ],
)
async def test_steps_that_keep_rows_keep_their_bounds(tables: Tables, sql: str) -> None:
    years = await tables.table("/years.csv", Roles(measures=(BOUNDED,)))

    step = await tables.transform(sql, years, roles=Roles(measures=(BOUNDED,)))

    assert step.output.roles.measures == (BOUNDED,)


# Geography

# The recipe of ada.core.services.schema.geo: an explicit join with the mapping, and the
# new code system and level declared on the result. A map starts from the boundaries, so
# a county without a value is still drawn, as missing.
TO_COUNTIES = """
SELECT b.county_code, b.name AS county, d.period_start, d.period_end, d.value, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id
ORDER BY county_code, period_start
"""
COUNTY_ROLES = Roles(
    time=TimeRole(start="period_start", end="period_end", grain=Grain.YEAR),
    geo=GeoRole(code="county_code", system=geo.STATFIN, level=geo.WELLBEING_SERVICES_COUNTY),
    measures=(MeasureRole(value="value"),),
)


async def test_a_measure_mapped_to_the_counties_feeds_a_map(tmp_path: Path) -> None:
    world = TimeWorld(tmp_path)
    screening = await world.operator(await world.register(SOTKANET_BREAST_SCREENING))
    regions = await world.operator(await world.register(SOTKANET_REGIONS))
    boundaries = await world.operator(await world.register(WELLBEING_COUNTY_BOUNDARIES))
    mapped = await world.transform(TO_COUNTIES, screening, regions, boundaries, roles=COUNTY_ROLES)
    widget = await world.widgets.create(
        world.project_id, mapped.id, "map", "Breast cancer screening, 2024", AGENT
    )

    data = await world.widgets.data(widget.id, (await world.run(2024, 2024)).id)

    names = [column.name for column in data.columns]
    rows = [dict(zip(names, row, strict=True)) for row in data.rows]
    assert len(rows) == 23
    value = {row["county_code"]: row["value"] for row in rows}
    # The spec's first gap: 74.3% in the City of Helsinki, 85.6% in North Ostrobothnia.
    assert (value["90"], value["19"]) == (74.3, 85.6)
    # Åland runs its own screening and Sotkanet has no value for it: drawn as missing.
    assert value["91"] is None
    assert data.output.roles.geo == COUNTY_ROLES.geo
    assert not data.is_stale
    # Sotkanet's own regions are of mixed levels: no map without the mapping.
    with pytest.raises(Invalid, match="mixed levels"):
        await world.widgets.create(world.project_id, screening.id, "map", "Screening", AGENT)


# Batches, over MCP on PostgreSQL: all or nothing is the transaction of the tool call.


def batch(sql: str = "SELECT region, sum(value) AS total FROM input_0 GROUP BY region") -> list:
    return [
        {
            "ref": "s",
            "register_source": {
                "name": "Regions",
                "address": "https://example.test/regions.csv",
                "declared_schema": DECLARED.model_dump(mode="json"),
                "provenance": {"publisher": "Example statistics", "licence": "CC BY 4.0"},
                "refresh": True,
            },
        },
        {"ref": "src", "source_operator": {"data_source_id": "$s"}, "note": "The raw regions"},
        {"ref": "t", "transform": {"sql": sql, "inputs": ["$src"]}, "note": "Totals"},
        {"ref": "w", "widget": {"operator": "$t", "type": "table", "title": "Totals"}},
    ]


@pytest.fixture
async def builder(
    migrated_database_url: str, tmp_path: Path
) -> AsyncIterator[tuple[Client, AsyncContainer]]:
    container = create_container(settings_in(tmp_path, migrated_database_url), MemoryBackground())
    info = Implementation(name="claude-code", version="1")
    try:
        async with Client(create_mcp(container), client_info=info) as client:
            yield client, container
    finally:
        await container.close()


async def test_a_batch_builds_everything_with_references_and_again_nothing_new(
    builder: tuple[Client, AsyncContainer],
) -> None:
    client, container = builder
    project = await call(client, "create_project", name="Batch")
    session = await call(client, "create_session", project_id=project["id"], title="Build")
    arguments = {"project_id": project["id"], "steps": batch(), "session_id": session["id"]}

    built = await call(client, "build_pipeline", **arguments)
    dispatcher = await container.get(TaskDispatcher)
    assert isinstance(dispatcher, RecordingTaskDispatcher)
    queued = list(dispatcher.refreshes)
    again = await call(client, "build_pipeline", **arguments)

    refs = built["refs"]
    assert again == built
    assert built["widgets"] == [
        {
            "id": refs["w"],
            "url": f"/projects/{project['id']}/sessions/{session['id']}?widget={refs['w']}",
        }
    ]
    lineage = await call(client, "get_lineage", session_id=session["id"], operator_id=refs["t"])
    assert [operator["id"] for operator in lineage] == [refs["src"], refs["t"]]
    assert lineage[0]["params"] == {"data_source_id": refs["s"]}
    # The registered source was not fetched in the batch, but queued after its commit.
    assert queued == [(UUID(refs["s"]), False)]
    async with container() as request:
        entries = await (await request.get(SessionService)).entries(UUID(session["id"]))
        sources = await (await request.get(SourceService)).list(UUID(project["id"]))
        widgets = await (await request.get(WidgetService)).list(UUID(project["id"]))
    # Each call is recorded after what it made; the second made nothing.
    calls = [(e.tool_call.tool, e.tool_call.status) for e in entries if e.tool_call is not None]
    assert [(e.kind, e.ref, e.text) for e in entries if e.kind != "tool_call"] == [
        ("operator", refs["src"], "The raw regions"),
        ("operator", refs["t"], "Totals"),
        ("widget", refs["w"], ""),
    ]
    assert [e.kind for e in entries][3:] == ["tool_call"] * 3
    assert calls == [("build_pipeline", "ok")] * 2 + [("get_lineage", "ok")]
    assert (len(sources), len(widgets)) == (1, 1)
    assert sources[0].provenance is not None
    assert (sources[0].provenance.publisher, sources[0].provenance.licence) == (
        "Example statistics",
        "CC BY 4.0",
    )

    history = await call(
        client,
        "add_history",
        project_id=project["id"],
        session_id=session["id"],
        source_id=refs["s"],
        last=3,
    )
    assert history["kind"] == "history"
    assert history["params"] == {"last": 3}
    assert history["inputs"] == [refs["src"]]
    assert [c["name"] for c in history["output"]["columns"]] == [
        "region",
        "value",
        "snapshot_at",
        "snapshot_rank",
    ]


async def test_a_batch_that_fails_midway_stores_nothing(
    builder: tuple[Client, AsyncContainer],
) -> None:
    client, container = builder
    project = await call(client, "create_project", name="Batch")
    session = await call(client, "create_session", project_id=project["id"], title="Build")
    where = {"project_id": project["id"], "session_id": session["id"]}
    broken = batch("SELECT nope FROM input_0")

    with pytest.raises(ToolError, match=r"steps\[2\] \(ref 't'\) failed.*nope"):
        await call(client, "build_pipeline", **where, steps=broken)
    later = batch()
    later[1]["source_operator"]["data_source_id"] = "$w"
    with pytest.raises(ToolError, match=r"steps\[1\].*\$w names no earlier step"):
        await call(client, "build_pipeline", **where, steps=later)

    assert await call(client, "list_sources", **where) == []
    assert await call(client, "list_pipelines", **where) == []
    dispatcher = await container.get(TaskDispatcher)
    assert isinstance(dispatcher, RecordingTaskDispatcher)
    assert dispatcher.refreshes == []


async def test_source_history_is_fixed_limited_and_cached(tmp_path: Path) -> None:
    world = World(tmp_path)
    source, operator = await world.sources.add(world.project_id, b"region\nHelsinki\n")
    await world.sources.refresh(source.id)
    world.clock.advance(days=1)
    world.sources.content[source.id] = b"region\nHelsinki\nTurku\n"
    await world.sources.refresh(source.id)
    old_run = await world.runs.start(world.project_id, AGENT)
    await world.runs.read(old_run.id, operator.id)
    history = await world.pipelines.add_history(world.project_id, source.id, AGENT)
    delta = await world.transform(
        "SELECT region FROM input_0 WHERE snapshot_rank = 1 "
        "EXCEPT SELECT region FROM input_0 WHERE snapshot_rank = 2",
        history,
        materialize=True,
    )
    assert await world.read(delta, old_run.id) == [("Turku",)]
    cached = len(world.store.materialized)
    assert await world.read(delta) == [("Turku",)]
    assert len(world.store.materialized) == cached

    world.clock.advance(days=1)
    world.sources.content[source.id] = b"region\nHelsinki\nTurku\nOulu\n"
    await world.sources.refresh(source.id)
    rows = await world.read(history)
    assert [row[2] for row in rows] == [1, 1, 1, 2, 2, 3]
    assert sorted((row[0], row[2]) for row in rows) == sorted(
        [
            ("Helsinki", 1),
            ("Turku", 1),
            ("Oulu", 1),
            ("Helsinki", 2),
            ("Turku", 2),
            ("Helsinki", 3),
        ]
    )
    assert rows[0][1] == world.clock.now().replace(tzinfo=None)
    assert {row[2] for row in await world.read(history, old_run.id)} == {1, 2}
    assert await world.read(delta) == [("Oulu",)]
    assert len(world.store.materialized) == cached + 1
    limited = await world.pipelines.add_history(world.project_id, source.id, AGENT, last=1)
    assert {row[2] for row in await world.read(limited)} == {1}
    assert not (await world.sources.refresh(source.id)).changed
    assert len(await world.snapshots.list(operator.id)) == 3
    assert await world.read(delta, old_run.id) == [("Turku",)]


async def test_source_history_schema_changes_and_validation(tmp_path: Path) -> None:
    world = World(tmp_path)
    source, _ = await world.sources.add(world.project_id, b"region,removed\nHelsinki,old\n")
    await world.sources.refresh(source.id)
    world.clock.advance(days=1)
    world.sources.content[source.id] = b"region,value\nTurku,10\n"
    await world.sources.refresh(source.id)
    history = await world.pipelines.add_history(world.project_id, source.id, AGENT)
    rows = await world.read(history)
    assert rows[0][:2] == ("Turku", 10)
    assert rows[1][:2] == ("Helsinki", None)
    removed = await world.transform("SELECT removed FROM input_0", history)
    assert await world.read(removed) == [(None,), ("old",)]
    for last in (0, -1):
        with pytest.raises(Invalid, match="positive integer"):
            await world.pipelines.add_history(world.project_id, source.id, AGENT, last=last)
    with pytest.raises(Invalid, match="another project"):
        await world.pipelines.add_history(uuid7(), source.id, AGENT)
    await world.data_sources.update(
        source.model_copy(update={"options": {"pushdown": {"param": "years"}}}), source.revision
    )
    with pytest.raises(Invalid, match="pushdown"):
        await world.pipelines.add_history(world.project_id, source.id, AGENT)

    reserved, _ = await world.sources.add(world.project_id, b"snapshot_rank\n1\n")
    with pytest.raises(Invalid, match="reserves"):
        await world.pipelines.add_history(world.project_id, reserved.id, AGENT)


async def test_source_history_refuses_a_source_changed_to_pushdown(tmp_path: Path) -> None:
    world = World(tmp_path)
    source, operator = await world.sources.add(world.project_id, REGIONS)
    history = await world.pipelines.add_history(world.project_id, source.id, AGENT)
    run = await world.runs.start(world.project_id, AGENT)
    await world.runs.read(run.id, operator.id)
    await world.data_sources.update(
        source.model_copy(update={"options": {"pushdown": {"param": "years"}}}), source.revision
    )
    with pytest.raises(
        Invalid, match=r"Source history does not support period \(pushdown\) sources"
    ):
        await world.runs.execute(run.id, history.id)
