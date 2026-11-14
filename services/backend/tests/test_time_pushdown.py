"""Pushing a run's time range down to a source: Sotkanet, answering from recorded responses,
is asked for the requested years only, stores each year as a snapshot, reuses stored
years and fetches only missing or stale ones. A source that cannot filter is read whole
and the run filters its rows instead."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pytest

from ada.adapters.sources.examples import NORDCAN_LUNG_SURVIVAL, SOTKANET_BREAST_SCREENING
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.events import EventType
from ada.core.models.schema import Column, ColumnType, Roles, Schema, TimeRole
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy
from ada.core.models.time import Grain, TimeRange
from ada.core.services.schema.time import year
from ada.core.services.sources.service import source_operator_id
from factories import AGENT
from time_world import World

pytestmark = pytest.mark.anyio

DAY = 24 * 60 * 60
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


async def test_a_probe_that_sees_no_change_keeps_every_stored_year(world: World) -> None:
    source = await world.register(SOTKANET_BREAST_SCREENING)
    operator = await world.operator(source)
    await world.rows(operator, await world.run(2023, 2024))
    world.requests()
    world.clock.advance(days=1)

    await world.rows(operator, await world.run(2023, 2024))

    # A day later the probe is due; the indicator's date has not moved, so nothing more.
    assert world.requests() == [PROBE]
    assert [s.fetched_at for s in world.period_snapshots(source)] == [
        world.clock.at.replace(day=14),
        world.clock.at.replace(day=14),
    ]


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


async def test_a_year_without_data_is_stored_empty(world: World) -> None:
    policy = FreshnessPolicy(kind=FreshnessKind.MANUAL)
    source = await world.register(SOTKANET_BREAST_SCREENING, freshness=policy)
    operator = await world.operator(source)
    world.replay.exchanges.append(
        {
            "method": "GET",
            "url": "https://sotkanet.fi/rest/1.1/json?indicator=3621&years=2024&years=2025"
            "&years=2026&genders=total",
            "status": 200,
            "content_type": "application/json",
            "body": "sotkanet-3621-2024.json",
        }
    )

    # An open end runs to the current year; Sotkanet has nothing after 2024 yet.
    run = await world.runs.start(world.project_id, AGENT, TimeRange(start=date(2024, 1, 1)))
    rows = await world.rows(operator, run)

    assert years_of(rows) == {2024: 440}
    counts = {s.parameters_key[7:11]: s.row_count for s in world.period_snapshots(source)}
    assert counts == {"2024": 440, "2025": 0, "2026": 0}
    # Stored as empty, so a manual source does not ask for them again.
    world.requests()
    await world.rows(operator, await world.runs.start(world.project_id, AGENT, run.time_range))
    assert world.requests() == []


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


async def test_a_run_without_a_range_reads_the_whole_source_as_before(world: World) -> None:
    source = await world.register(SOTKANET_BREAST_SCREENING)
    operator = await world.operator(source)

    rows = await world.rows(operator, await world.run())

    # The address's own years, fetched whole and kept under the empty key.
    assert world.requests() == [PROBE, years(2023, 2024)]
    assert len(rows) == 880
    assert world.period_snapshots(source) == []
    assert await world.snapshots.current(operator.id, "") is not None


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


async def test_downstream_steps_follow_the_range_and_only_where_it_matters(
    world: World,
) -> None:
    nordcan = await world.operator(await world.register(NORDCAN_LUNG_SURVIVAL))
    finland = await world.transform(
        "SELECT period, sex, survival FROM input_0 WHERE country = 'Finland'",
        nordcan,
        materialize=True,
    )

    recent = await world.rows(finland, await world.run(2020, 2024))
    everything = await world.rows(finland, await world.run())

    assert {row["period"] for row in recent} == {"2020-2024"}
    assert len(recent) == 2 and len(everything) > len(recent)
    # Two ranges, two materialized results: the range is part of what the step read.
    keys = {
        s.parameters_key for s in world.memory.snapshots.values() if s.operator_id == finland.id
    }
    assert len(keys) == 2


async def test_a_range_that_ends_before_it_starts_is_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="ends"):
        await world.runs.start(
            world.project_id,
            AGENT,
            TimeRange(start=date(2024, 1, 1), end=date(2023, 1, 1)),
        )


# The request body: a PxWeb-style query whose time selection takes the periods.

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
        (
            {
                "declared_schema": DECLARED.model_copy(
                    update={"roles": Roles(time=TimeRole(start="period_start", end="period_end"))}
                )
            },
            "grain",
        ),
        ({"options": {"pushdown": {}}}, "either"),
        ({"options": {"pushdown": {"param": "y", "body": "x"}}}, "either"),
        ({"options": {"pushdown": {"body": "query"}}}, "request source"),
        ({"options": {"pushdown": {"param": "y", "format": "{decade}"}}}, "format"),
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


async def test_a_body_path_must_exist(world: World) -> None:
    with pytest.raises(Invalid, match="nothing at"):
        await world.sources.register(
            world.project_id,
            name="Deaths",
            access_kind=AccessKind.REQUEST,
            address="https://example.test/table.px",
            format=DataFormat.CSV,
            options={"body": QUERY, "pushdown": {"body": "query.5.selection.values"}},
            declared_schema=DECLARED,
        )
