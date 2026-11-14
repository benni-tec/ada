"""Time: periods as intervals, the `period` shaping option, and pushing a run's time range
down to a source (Sotkanet, answering from recorded responses, is asked for the requested
years only, stores each year as a snapshot and fetches only missing or stale ones), on the
memory repositories and on PostgreSQL."""

import asyncio
import csv
import io
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import factories
from ada.adapters.db.workspace_repositories import SqlSourceCheckLog, SqlSourceLocks
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemorySourceLocks
from ada.adapters.secrets.fernet import FernetSecretBox
from ada.adapters.sources.examples import NORDCAN_LUNG_SURVIVAL, SOTKANET_BREAST_SCREENING
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.models.analysis import FetchedData
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.events import EventType
from ada.core.models.runs import Snapshot
from ada.core.models.schema import Column, ColumnType, Roles, Schema, TimeRole
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy
from ada.core.models.time import Grain, Interval, TimeRange
from ada.core.services.pipelines.runs import Runs
from ada.core.services.schema.time import label, parse_period, periods, year
from ada.core.services.sources.service import DataSources, source_operator_id
from ada.core.services.sources.shaping import shape, split_periods
from db_helpers import Repos, engine_for, sql_repos, unit_of_work
from factories import AGENT
from fakes import FakeExplorer, FixedClock, Replay
from time_world import TODAY, World

pytestmark = pytest.mark.anyio

DAY = 24 * 60 * 60


# Periods


def span(start: str, end: str) -> Interval:
    return Interval(start=date.fromisoformat(start), end=date.fromisoformat(end))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2024, span("2024-01-01", "2024-12-31")),
        # A multi-year window is one period, however it is written.
        ("2020-2024", span("2020-01-01", "2024-12-31")),
        ("2024Q1", span("2024-01-01", "2024-03-31")),
        ("2024M02", span("2024-02-01", "2024-02-29")),
        (date(2024, 3, 15), span("2024-03-15", "2024-03-15")),
    ],
)
def test_a_source_s_period_is_read_as_an_interval(value: object, expected: Interval) -> None:
    assert parse_period(value) == expected


@pytest.mark.parametrize("value", ["soon", "2024-2020", "2024Q5", 2024.5])
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(ValueError):
        parse_period(value)


def test_a_range_splits_into_every_period_it_overlaps() -> None:
    years = periods(TimeRange(start=date(2022, 6, 1), end=date(2024, 2, 1)), Grain.YEAR, date.max)
    assert years == (
        span("2022-01-01", "2022-12-31"),
        span("2023-01-01", "2023-12-31"),
        span("2024-01-01", "2024-12-31"),
    )
    quarters = periods(
        TimeRange(start=date(2023, 11, 1), end=date(2024, 4, 1)), Grain.QUARTER, date.max
    )
    assert [label(q, Grain.QUARTER) for q in quarters] == ["2023Q4", "2024Q1", "2024Q2"]
    months = periods(
        TimeRange(start=date(2023, 12, 5), end=date(2024, 1, 5)), Grain.MONTH, date.max
    )
    assert [label(m, Grain.MONTH) for m in months] == ["2023M12", "2024M01"]


def fetched(content: bytes, format: DataFormat = DataFormat.JSON) -> FetchedData:
    return FetchedData(
        content=content, format=format, fetched_at=datetime(2026, 1, 1, tzinfo=UTC), origin="x"
    )


def test_the_period_option_adds_the_time_role_s_columns_to_json() -> None:
    data = fetched(
        json.dumps([{"year": 2023, "v": 1}, {"year": "2024", "v": 2}, {"v": 3}]).encode()
    )

    shaped = shape(data, {"period": {"column": "year"}})

    assert json.loads(shaped.content) == [
        {"year": 2023, "v": 1, "period_start": "2023-01-01", "period_end": "2023-12-31"},
        {"year": "2024", "v": 2, "period_start": "2024-01-01", "period_end": "2024-12-31"},
        # No value, no period: the row is in no bounded range.
        {"year": None, "v": 3, "period_start": None, "period_end": None},
    ]


def test_the_period_option_works_on_csv_too() -> None:
    data = fetched(b"\xef\xbb\xbfquarter;n\n2024Q1;5\n2024Q2;..\n", DataFormat.CSV)
    options = {
        "csv": {"delimiter": ";", "null_values": [".."]},
        "period": {"column": "quarter"},
    }

    shaped = shape(data, options)

    assert list(csv.reader(io.StringIO(shaped.content.decode()))) == [
        ["quarter", "n", "period_start", "period_end"],
        ["2024Q1", "5", "2024-01-01", "2024-03-31"],
        ["2024Q2", "", "2024-04-01", "2024-06-30"],
    ]
    # Without `csv` the period option still parses the CSV, with its defaults.
    plain = shape(fetched(b"year,n\n2024,5\n", DataFormat.CSV), {"period": {"column": "year"}})
    assert plain.content == b"year,n,period_start,period_end\n2024,5,2024-01-01,2024-12-31\n"


ROLE = TimeRole(start="period_start", end="period_end", grain=Grain.YEAR)
Y2023, Y2024 = span("2023-01-01", "2023-12-31"), span("2024-01-01", "2024-12-31")


def test_an_answer_for_several_periods_is_split_by_period() -> None:
    rows = [
        {"v": 1, "period_start": "2023-01-01", "period_end": "2023-12-31"},
        {"v": 2, "period_start": "2024-01-01", "period_end": "2024-12-31"},
        {"v": 3, "period_start": "2023-01-01", "period_end": "2023-12-31"},
    ]
    parts = split_periods(fetched(json.dumps(rows).encode()), ROLE, [Y2023, Y2024])

    assert {p: [r["v"] for r in json.loads(d.content)] for p, d in parts.items()} == {
        Y2023: [1, 3],
        Y2024: [2],
    }
    table = b"v,period_start,period_end\n1,2024-01-01,2024-12-31\n"
    [(period, part)] = split_periods(fetched(table, DataFormat.CSV), ROLE, [Y2023, Y2024]).items()
    assert (period, part.content) == (Y2024, table)


# Pushdown


PROBE = "/rest/1.1/indicators/3621?"


def years(*numbers: int) -> str:
    query = "&".join(sorted(["genders=total", "indicator=3621", *(f"years={n}" for n in numbers)]))
    return f"/rest/1.1/json?{query}"


def years_of(rows: list[dict[str, object]]) -> Counter[int]:
    return Counter(int(str(row["period_start"])[:4]) for row in rows)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


async def test_a_run_asks_sotkanet_for_the_requested_years_only(world: World) -> None:
    source = await world.register(SOTKANET_BREAST_SCREENING)
    operator = await world.operator(source)

    run = await world.run(2023, 2024)
    rows = await world.rows(operator, run)

    # The probe records the token the data is fetched under, then one request for both.
    assert world.requests() == [PROBE, years(2023, 2024)]
    assert years_of(rows) == {2023: 440, 2024: 440}
    # One snapshot per period, named by it, and the run fixed their union.
    [y2023, y2024] = world.period_snapshots(source)
    assert (y2023.parameters_key, y2023.period) == (
        "period:2023-01-01/2023-12-31",
        year(2023),
    )
    assert (y2024.row_count, y2024.period) == (440, year(2024))
    fixed = world.memory.snapshots[(await world.runs.get(run.id)).snapshots[operator.id]]
    assert fixed.parameters_key.startswith("range:")
    assert fixed.row_count == 880
    assert (await world.sources.get(source.id)).last_probe_token == "2026-06-12"


async def test_a_wider_range_reuses_the_stored_years_and_fetches_the_missing_one(
    world: World,
) -> None:
    source = await world.register(SOTKANET_BREAST_SCREENING)
    operator = await world.operator(source)
    await world.rows(operator, await world.run(2023, 2024))
    world.requests()

    rows = await world.rows(operator, await world.run(2022, 2024))

    assert world.requests() == [years(2022)]
    assert years_of(rows) == {2022: 440, 2023: 440, 2024: 440}
    # The same range again: everything is stored and fresh, nothing is fetched.
    again = await world.rows(operator, await world.run(2022, 2024))
    assert world.requests() == []
    assert again == rows
    # A narrower range is served from the stored years too.
    assert years_of(await world.rows(operator, await world.run(2024, 2024))) == {2024: 440}
    assert world.requests() == []


async def test_a_changed_probe_token_refetches_the_years_and_retires_the_rest(
    world: World,
) -> None:
    source = await world.register(SOTKANET_BREAST_SCREENING)
    operator = await world.operator(source)
    await world.rows(operator, await world.run(2023, 2024))
    await world.rows(operator, await world.run(2022, 2024))
    await world.sources.refresh(source.id)
    world.requests()
    # As if the indicator was updated since: the stored token is an older date.
    await world.data_sources.record_check(source.id, world.clock.now(), "2026-01-01", None)
    world.clock.advance(days=1)

    await world.rows(operator, await world.run(2023, 2024))

    assert world.requests() == [PROBE, years(2023, 2024)]
    current = {s.parameters_key for s in world.period_snapshots(source)}
    assert current == {"period:2023-01-01/2023-12-31", "period:2024-01-01/2024-12-31"}
    # 2022 and the whole-source snapshot predate the change: fetched again when asked for.
    assert await world.snapshots.current(source_operator_id(source), "") is None
    assert (await world.sources.get(source.id)).last_probe_token == "2026-06-12"


async def test_the_newest_year_has_a_shorter_lifetime(world: World) -> None:
    policy = FreshnessPolicy(
        kind=FreshnessKind.TTL, ttl_seconds=30 * DAY, latest_period_ttl_seconds=DAY
    )
    source = await world.register(SOTKANET_BREAST_SCREENING, freshness=policy)
    operator = await world.operator(source)
    first = await world.run(2023, 2024)
    await world.rows(operator, first)
    world.requests()
    world.clock.advance(days=1)

    second = await world.run(2023, 2024)
    rows = await world.rows(operator, second)

    # 2024 is the newest year with data, so it is a day old and stale; 2023 lives 30 days.
    assert world.requests() == [years(2024)]
    assert years_of(rows) == {2023: 440, 2024: 440}
    snapshots = world.period_snapshots(source, current=False)
    assert [s.parameters_key[7:11] for s in snapshots] == ["2023", "2024", "2024"]
    old_2024, new_2024 = snapshots[1:]
    assert old_2024.superseded_at is not None and new_2024.superseded_at is None
    # The year came back the same: same content, same file, and the same union, so the
    # runs read identical data and nothing downstream has to run again.
    assert new_2024.content_hash == old_2024.content_hash
    assert (await world.runs.get(second.id)).snapshots == (await world.runs.get(first.id)).snapshots
    refreshed = [e for e in world.events.published if e.type is EventType.SOURCE_REFRESHED]
    assert [e.payload["changed"] for e in refreshed] == [True, False]


async def test_a_failed_fetch_serves_the_stored_years_and_marks_them_stale(
    world: World,
) -> None:
    policy = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=DAY)
    source = await world.register(SOTKANET_BREAST_SCREENING, freshness=policy)
    operator = await world.operator(source)
    await world.rows(operator, await world.run(2023, 2024))
    widget = await world.widgets.create(world.project_id, operator.id, "table", "Screening", AGENT)
    world.clock.advance(days=2)
    world.transport.down = True

    run = await world.run(2023, 2024)
    data = await world.widgets.data(widget.id, run.id)

    assert len(data.rows) == 880
    assert data.is_stale
    assert "the source is down" in ((await world.sources.get(source.id)).last_error or "")
    # A year that was never stored has nothing to serve: the run fails.
    with pytest.raises(Unavailable):
        await world.rows(operator, await world.run(2022, 2024))


async def test_a_source_that_cannot_filter_is_filtered_by_the_run(world: World) -> None:
    source = await world.register(NORDCAN_LUNG_SURVIVAL)
    operator = await world.operator(source)

    run = await world.run(2015, 2024)
    rows = await world.rows(operator, run)

    # NORDCAN answers with every five-year window; the run keeps those that overlap.
    assert {row["period"] for row in rows} == {"2015-2019", "2020-2024"}
    assert len(rows) == 4 * 2 * 2
    fixed = world.memory.snapshots[(await world.runs.get(run.id)).snapshots[operator.id]]
    assert (fixed.parameters_key, fixed.row_count) == ("", 76)
    # A window reaching into the range counts: 2024 alone still shows 2020-2024.
    latest = await world.rows(operator, await world.run(2024, 2024))
    assert {row["period"] for row in latest} == {"2020-2024"}
    # Without a range, everything.
    assert len(await world.rows(operator, await world.run())) == 76


QUERY = {
    "query": [
        {"code": "Alue", "selection": {"filter": "all", "values": ["*"]}},
        {"code": "Vuosi", "selection": {"filter": "item", "values": ["2020"]}},
    ],
    "response": {"format": "csv"},
}


DECLARED = Schema(
    columns=(
        Column(name="area", type=ColumnType.TEXT),
        Column(name="year", type=ColumnType.INTEGER),
        Column(name="deaths", type=ColumnType.INTEGER),
        Column(name="period_start", type=ColumnType.DATE),
        Column(name="period_end", type=ColumnType.DATE),
    ),
    roles=Roles(time=TimeRole(start="period_start", end="period_end", grain=Grain.YEAR)),
)


async def test_pushdown_into_a_request_body(tmp_path: Path) -> None:
    asked: list[list[str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        values = json.loads(request.content)["query"][1]["selection"]["values"]
        asked.append(values)
        lines = ["area;year;deaths", *(f"North;{year};{int(year) - 2000}" for year in values)]
        return httpx.Response(200, content="\n".join(lines).encode())

    world = World(tmp_path, transport=httpx.MockTransport(answer))
    source = await world.sources.register(
        world.project_id,
        name="Deaths",
        access_kind=AccessKind.REQUEST,
        address="https://pxdata.example/table.px",
        format=DataFormat.CSV,
        options={
            "body": QUERY,
            "csv": {"delimiter": ";"},
            "period": {"column": "year"},
            "pushdown": {"body": "query.1.selection.values"},
        },
        declared_schema=DECLARED,
    )
    operator = await world.operator(source)

    rows = await world.rows(operator, await world.run(2022, 2023))
    await world.rows(operator, await world.run(2021, 2023))

    assert asked == [["2022", "2023"], ["2021"]]
    assert [(row["year"], row["deaths"]) for row in rows] == [(2022, 22), (2023, 23)]
    assert isinstance(rows[0]["period_start"], date)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"declared_schema": None}, "time role that has a grain"),
        ({"options": {"pushdown": {"body": "query"}}}, "request source"),
    ],
)
async def test_pushdown_options_that_cannot_work_are_refused_at_registration(
    world: World, changes: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {
        "name": "Deaths",
        "access_kind": AccessKind.URL,
        "address": "https://example.test/data.csv",
        "format": DataFormat.CSV,
        "options": {"pushdown": {"param": "years"}},
        "declared_schema": DECLARED,
    }
    with pytest.raises(Invalid, match=message):
        await world.sources.register(world.project_id, **(arguments | changes))  # type: ignore[arg-type]


# On PostgreSQL


async def test_a_refetched_period_replaces_the_stored_one(
    migrated_database_url: str, tmp_path: Path
) -> None:
    clock = FixedClock(TODAY)
    replay = Replay()
    readers = HttpSourceReaders(create_client(httpx.MockTransport(replay)), clock)
    store = DuckDbAnalysisStore(tmp_path / "data")
    years = TimeRange(start=date(2023, 1, 1), end=date(2024, 12, 31))
    policy = FreshnessPolicy(
        kind=FreshnessKind.TTL, ttl_seconds=30 * DAY, latest_period_ttl_seconds=DAY
    )

    async with engine_for(migrated_database_url) as engine:

        def services(repos: Repos) -> tuple[DataSources, Runs]:
            events = MemoryEventBus()
            sources = DataSources(
                repos.projects,
                repos.data_sources,
                repos.operators,
                repos.snapshots,
                readers,
                SqlSourceCheckLog(engine),
                store,
                events,
                clock,
                MemorySourceLocks(),
                FakeExplorer(),
                FernetSecretBox(None),
                None,
            )
            runs = Runs(repos.runs, repos.operators, repos.snapshots, sources, store, events, clock)
            return sources, runs

        async with unit_of_work(engine) as repos:
            project = factories.project()
            await repos.projects.add(project)
            sources, runs = services(repos)
            source = await sources.register(
                project.id, **(SOTKANET_BREAST_SCREENING.registration() | {"freshness": policy})
            )
            run = await runs.start(project.id, AGENT, years)
            first = await runs.read(run.id, source_operator_id(source), 2000)

        clock.advance(days=1)
        async with unit_of_work(engine) as repos:
            sources, runs = services(repos)
            run = await runs.start(project.id, AGENT, years)
            second = await runs.read(run.id, source_operator_id(source), 2000)
            snapshots = await repos.snapshots.list(source_operator_id(source))

    assert len(first.rows) == len(second.rows) == 880
    periods = [s for s in snapshots if s.parameters_key.startswith("period:")]
    # 2023 once; 2024 twice, the first retired when the second came.
    assert sorted((s.parameters_key[7:11], s.superseded_at is None) for s in periods) == [
        ("2023", True),
        ("2024", False),
        ("2024", True),
    ]
    assert all(s.period is not None for s in periods)


async def test_two_runs_that_want_the_same_missing_periods_fetch_them_once(
    migrated_database_url: str, tmp_path: Path
) -> None:
    clock = FixedClock(TODAY)
    replay = Replay()
    asked: list[httpx.Request] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        # Slow enough that the second run starts while the first is still fetching.
        asked.append(request)
        await asyncio.sleep(0.2)
        return replay(request)

    readers = HttpSourceReaders(create_client(httpx.MockTransport(slow)), clock)
    store = DuckDbAnalysisStore(tmp_path / "data")
    years = TimeRange(start=date(2023, 1, 1), end=date(2024, 12, 31))
    only_2024 = TimeRange(start=date(2024, 1, 1), end=date(2024, 12, 31))
    policy = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=30 * DAY)

    async with engine_for(migrated_database_url) as engine:

        def service(session: AsyncSession) -> DataSources:
            repos = sql_repos(session)
            return DataSources(
                repos.projects,
                repos.data_sources,
                repos.operators,
                repos.snapshots,
                readers,
                SqlSourceCheckLog(engine),
                store,
                MemoryEventBus(),
                clock,
                SqlSourceLocks(session),
                FakeExplorer(),
                FernetSecretBox(None),
                None,
            )

        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            project = factories.project()
            await sql_repos(session).projects.add(project)
            source = await service(session).register(
                project.id, **(SOTKANET_BREAST_SCREENING.registration() | {"freshness": policy})
            )

        async def run(range: TimeRange = years) -> Snapshot | None:
            async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
                return await service(session).refresh_range(source.id, range)

        first, second = await asyncio.gather(run(), run(years))
        # 2024 alone is stored and fresh: two runs at once only put its union together, and
        # the second finds the first's.
        third, fourth = await asyncio.gather(run(only_2024), run(only_2024))

    assert third is not None and fourth is not None and third.id == fourth.id
    # The second waited for the first and found its periods: one request, one union.
    assert [request.url.params.get_list("years") for request in asked] == [["2023", "2024"]]
    assert first is not None and second is not None
    assert first.content_hash == second.content_hash
