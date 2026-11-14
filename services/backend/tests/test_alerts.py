"""Alerts: the formula tree (validated against the measure's schema, compiled to SQL and run
on DuckDB the way a fused query runs it), the alert service over the real pipeline, run
and source services (alerts_support.py), the REST routes and MCP tools, PostgreSQL, and
the worker checking due rules."""

from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import duckdb
import pytest
from cryptography.fernet import Fernet
from dishka import AsyncContainer, Provider, Scope
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import SecretStr
from taskiq import AsyncBroker

from ada.adapters.valkey.tasks import ValkeyTaskDispatcher
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState, Severity
from ada.core.models.errors import Conflict, Invalid, NotFound
from ada.core.models.events import EventType
from ada.core.models.schema import Column, ColumnType, MeasureRole, Roles, Schema, TimeRole
from ada.core.ports.repositories import OperatorRepository, RunRepository
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.alerts.formula import compile_rule, describe
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker import create_broker
from ada.entrypoints.worker.factory import ContainerMiddleware
from alerts_support import MEASURE, TESTER, AlertOverrides, Setup, World, below, csv
from api_support import call
from conftest import settings_in
from fakes import context_signature
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio

# The formula

SERIES = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="start", type=ColumnType.DATE),
        Column(name="end", type=ColumnType.DATE),
        Column(name="value", type=ColumnType.NUMBER),
        Column(name="count", type=ColumnType.INTEGER),
        Column(name="hidden", type=ColumnType.BOOLEAN),
        Column(name="extra", type=ColumnType.JSON),
    ),
    roles=Roles(
        time=TimeRole(start="start", end="end"),
        measures=(MeasureRole(value="value", suppressed="hidden"),),
    ),
)
FLAT = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="value", type=ColumnType.NUMBER),
    )
)
KEY = ("region",)


# Builders, so each test states only its tree.


def col(name: str, id: str | None = None) -> dict[str, Any]:
    return {"id": id or f"col-{name}", "kind": "column", "column": name}


def const(value: object, id: str = "const", **extra: Any) -> dict[str, Any]:
    return {"id": id, "kind": "constant", "value": value, **extra}


def cmp(op: str, left: dict[str, Any], right: dict[str, Any], id: str = "cmp") -> dict[str, Any]:
    return {"id": id, "kind": "compare", "op": op, "args": [left, right]}


def arith(op: str, left: dict[str, Any], right: dict[str, Any], id: str = "ar") -> dict[str, Any]:
    return {"id": id, "kind": "arithmetic", "op": op, "args": [left, right]}


def fn(kind: str, arg: dict[str, Any], periods: int = 1, id: str | None = None) -> dict[str, Any]:
    return {"id": id or kind, "kind": kind, "periods": periods, "args": [arg]}


def logic(kind: str, *args: dict[str, Any], id: str | None = None) -> dict[str, Any]:
    return {"id": id or kind, "kind": kind, "args": list(args)}


# Data: (region, year, value, hidden)

Row = tuple[str, int, float | None, bool]


def alerting(
    formula: dict[str, Any],
    rows: Sequence[Row],
    key: tuple[str, ...] = KEY,
    schema: Schema = SERIES,
) -> list[tuple[Any, ...]]:
    """The (region, year) of the rows that alert."""
    compiled = compile_rule(formula, schema, key)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            'CREATE TABLE measure (region VARCHAR, start DATE, "end" DATE, value DOUBLE, '
            "count BIGINT, hidden BOOLEAN, extra JSON)"
        )
        for region, year, value, hidden in rows:
            connection.execute(
                "INSERT INTO measure VALUES (?, ?, ?, ?, 1, ?, '{}')",
                [region, date(year, 1, 1), date(year, 12, 31), value, hidden],
            )
        if schema is FLAT:
            source = "SELECT region, value FROM measure"
        else:
            source = "SELECT * FROM measure"
        relation = connection.sql(f"WITH input_0 AS ({source}) SELECT * FROM (\n{compiled.sql}\n)")
        names = relation.columns
        result = relation.fetchall()
    expected = [c.name for c in schema.columns]
    assert names == expected, "the alerting rows have exactly the measure's columns"
    if schema is FLAT:
        return [(row[0], row[1]) for row in result]
    return [(row[0], row[1].year) for row in result]


def series(region: str, *values: float | None, first: int = 2020) -> list[Row]:
    return [(region, first + i, value, value is None) for i, value in enumerate(values)]


# Validation


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        (cmp("<", col("nope"), const(1)), "Formula node 'col-nope': 'nope' is not a column"),
        (
            cmp("<", col("region"), const(1)),
            "Formula node 'cmp': cannot compare a text with a number",
        ),
        (col("value"), "Formula node 'col-value': the condition must be true or false"),
        ({"id": "x", "kind": "magic"}, "Formula node 'x': unknown kind 'magic'"),
        (
            cmp("<", col("value", "same"), const(1, "same")),
            "Formula node 'same': the id is used twice",
        ),
        (cmp("<", fn("change", col("value"), periods=0), const(1)), "periods must be"),
    ],
)
def test_invalid_formulas_name_the_node_at_fault(formula: Any, message: str) -> None:
    with pytest.raises(Invalid, match=message):
        compile_rule(formula, SERIES, KEY)


def test_large_and_deep_formulas_are_rejected() -> None:
    wide = logic(
        "and", *[cmp("<", col("value", f"v{i}"), const(1, f"c{i}"), f"p{i}") for i in range(80)]
    )
    with pytest.raises(Invalid, match="at most 200 nodes"):
        compile_rule(wide, SERIES, KEY)
    deep: dict[str, Any] = col("hidden", "leaf")
    for i in range(40):
        deep = logic("not", deep, id=f"n{i}")
    with pytest.raises(Invalid, match="nests deeper"):
        compile_rule(deep, SERIES, KEY)


def test_the_condition_reads_as_text() -> None:
    formula = logic(
        "or",
        cmp("<", col("value"), const(80), id="low"),
        cmp("<=", fn("change", col("value", "v2"), periods=2), const(-5, "c5"), id="drop"),
        logic("not", col("hidden"), id="shown"),
    )
    assert describe(formula, SERIES) == (
        "value < 80 or change(value, 2 periods) <= -5 or not hidden"
    )
    assert compile_rule(formula, SERIES, KEY).condition == describe(formula, SERIES)
    plus = arith("+", col("value"), const(1, "one"), id="plus")
    nested = cmp("<", arith("*", plus, const(2), id="times"), const(3, "c3"))
    assert describe(nested, SERIES) == "(value + 1) * 2 < 3"
    minus = arith("-", col("value"), arith("-", col("count"), const(1, "one"), id="in"), id="out")
    assert describe(cmp(">", minus, const(0)), SERIES) == "value - (count - 1) > 0"


def test_comparisons_and_constants() -> None:
    rows = series("north", 90, 70) + series("south", 85, 95)
    assert alerting(cmp("<", col("value"), const(80)), rows) == [("north", 2021)]
    assert alerting(cmp(">=", col("value"), const(95)), rows) == [("south", 2021)]
    assert alerting(cmp("=", col("region"), const("south")), rows) == [("south", 2021)]
    assert alerting(cmp("!=", col("region"), const("south")), rows) == [("north", 2021)]
    # Integer columns compare with numbers.
    assert alerting(cmp("=", col("count"), const(1)), rows) == [("north", 2021), ("south", 2021)]
    after = cmp(">", col("start"), const("2021-06-01", type="date"))
    assert alerting(after, rows) == []
    # Text with a quote is a literal, not SQL.
    assert alerting(cmp("=", col("region"), const("x' OR 1=1 --")), rows) == []


def test_arithmetic_and_logic() -> None:
    rows = series("north", 10) + series("south", 30)
    doubled = cmp(">", arith("*", col("value"), const(2, "two")), const(50))
    assert alerting(doubled, rows) == [("south", 2020)]
    minus = cmp("<", arith("-", col("value"), const(20, "c20")), const(0))
    assert alerting(minus, rows) == [("north", 2020)]
    share = cmp(">", arith("/", col("value"), const(60, "c60")), const(0.4))
    assert alerting(share, rows) == [("south", 2020)]
    # Dividing by zero is unknown and never alerts; it does not fail the check.
    by_zero = cmp(">", arith("/", col("value"), const(0, "zero")), const(0))
    assert alerting(by_zero, rows) == []
    rows = series("north", 10) + series("south", 30) + series("east", 50)
    low = cmp("<", col("value"), const(20, "c20"), id="low")
    high = cmp(">", col("value", "v2"), const(40, "c40"), id="high")
    assert alerting(logic("or", low, high), rows) == [("east", 2020), ("north", 2020)]
    assert alerting(logic("and", low, high), rows) == []
    assert alerting(logic("not", logic("or", low, high)), rows) == [("south", 2020)]


def test_previous_period_is_the_previous_row_of_the_same_key() -> None:
    # Rows arrive out of order and interleaved; the window orders them by period start.
    rows = [
        ("north", 2022, 70.0, False),
        ("south", 2021, 60.0, False),
        ("north", 2021, 90.0, False),
        ("south", 2022, 65.0, False),
    ]
    fell = cmp("<", col("value"), fn("previous", col("value", "v2")))
    assert alerting(fell, rows) == [("north", 2022)]
    two_back = [*series("north", 90, 50, 60), *series("south", 70, 10, 80)]
    below_two_ago = cmp("<", col("value"), fn("previous", col("value", "v2"), periods=2))
    assert alerting(below_two_ago, two_back) == [("north", 2022)]


def test_change_over_n_periods() -> None:
    rows = series("north", 80, 79, 74) + series("south", 80, 82, 81)
    dropped = cmp("<=", fn("change", col("value")), const(-5))
    assert alerting(dropped, rows) == [("north", 2022)]
    dropped_over_two = cmp("<=", fn("change", col("value"), periods=2), const(-5))
    assert alerting(dropped_over_two, rows) == [("north", 2022)]
    # Without enough history the change is unknown, which does not alert.
    assert alerting(cmp("<", fn("change", col("value"), periods=5), const(0)), rows) == []


def test_rolling_mean_needs_a_full_window() -> None:
    rows = series("north", 90, 60, 60) + series("south", 60, 60)
    below = cmp("<", fn("rolling_mean", col("value"), periods=3), const(75))
    # north: (90 + 60 + 60) / 3 = 70. south has only two periods, so no mean yet.
    assert alerting(below, rows) == [("north", 2022)]


def test_time_functions_nest() -> None:
    # The change of the change: the drop got steeper.
    rows = series("north", 100, 98, 90) + series("south", 100, 90, 85)
    steeper = cmp("<", fn("change", fn("change", col("value"), id="inner"), id="outer"), const(0))
    assert alerting(steeper, rows) == [("north", 2022)]
    # A window over an expression that holds another window.
    mixed = cmp(
        "<",
        fn(
            "previous",
            arith("-", col("value"), fn("previous", col("value", "v2"), id="p1")),
            id="p2",
        ),
        const(-5),
    )
    # The step before the latest: north -2, south -10.
    assert alerting(mixed, rows) == [("south", 2022)]


def test_only_each_keys_latest_period_alerts() -> None:
    # north was low in 2020 only; south's data ends a year earlier and is low in its last.
    rows = series("north", 10, 90, 90) + series("south", 90, 10)
    assert alerting(cmp("<", col("value"), const(50)), rows) == [("south", 2021)]


def test_without_a_key_the_measure_is_one_series_and_without_time_every_row() -> None:
    rows = [("north", 2020, 90.0, False), ("south", 2021, 70.0, False)]
    fell = cmp("<", fn("change", col("value")), const(0))
    assert alerting(fell, rows, key=()) == [("south", 2021)]
    # Without a time role every row is evaluated.
    rows = series("north", 10, 90) + series("south", 90)
    assert alerting(cmp("<", col("value"), const(50)), rows, schema=FLAT) == [("north", 10.0)]


def test_suppressed_values_never_alert_nor_feed_a_time_function() -> None:
    rows = [*series("north", 80, None), *series("south", 90, 40)]
    # Withheld values are NULL in the data; a NOT around them must still not alert.
    unknown = logic("not", cmp(">=", col("value"), const(50)))
    assert alerting(unknown, rows) == [("south", 2021)]
    # Even when the condition does not depend on the value, a row whose measure the
    # formula reads and is withheld does not alert.
    either = logic(
        "or",
        cmp("<", col("value"), const(50), id="low"),
        cmp("=", col("region"), const("north", "n"), id="north"),
    )
    assert alerting(either, rows) == [("south", 2021)]
    # The flag withholds the value even where the data still carries one.
    flagged: list[Row] = [
        ("north", 2020, 99.0, True),
        ("north", 2021, 60.0, False),
        ("south", 2020, 90.0, False),
        ("south", 2021, 60.0, False),
    ]
    dropped = cmp("<", fn("change", col("value")), const(-10))
    assert alerting(dropped, flagged) == [("south", 2021)]


# The service

START = csv(("north", 2023, 85), ("north", 2024, 70), ("south", 2023, 90), ("south", 2024, 92))


@pytest.fixture
async def world(unreachable_settings: Settings) -> AsyncIterator[World]:
    overrides = AlertOverrides()
    settings = unreachable_settings.model_copy(
        update={
            "ada_public_url": "https://ada.example",
            "secret_key": SecretStr(Fernet.generate_key().decode()),
        }
    )
    container = create_container(settings, *memory_adapters(), overrides)
    try:
        yield World(container, overrides)
    finally:
        await container.close()


@pytest.fixture
async def setup(world: World) -> Setup:
    return await world.setup(START)


async def test_a_rule_is_created_and_is_not_an_operator(world: World, setup: Setup) -> None:
    rule = await world.rule(setup, severity=Severity.CRITICAL, check_interval_seconds=3600)

    assert (rule.project_id, rule.dashboard_id) == (setup.project_id, setup.dashboard.id)
    assert (rule.key_columns, rule.severity, rule.revision) == (
        ("region",),
        Severity.CRITICAL,
        1,
    )
    async with world.alerts() as service:
        assert await service.list_rules(setup.dashboard.id) == [rule]
    # The condition is the rule's, not an operator: the measure stays the only one.
    async with world.container() as request:
        operators = await (await request.get(OperatorRepository)).list(setup.project_id)
    assert not any(setup.measure.id in operator.inputs for operator in operators)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"formula": below(80) | {"args": [{"id": "x", "kind": "column", "column": "nope"}, 1]}},
            "Formula node 'x'",
        ),
        ({"alert_pipeline_id": "op_missing"}, "alert pipeline op_missing does not exist"),
    ],
)
async def test_invalid_rules_are_rejected(
    world: World, setup: Setup, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(Invalid, match=message):
        await world.rule(setup, **changes)
    async with world.alerts() as service:
        assert await service.list_rules(setup.dashboard.id) == []
        with pytest.raises(NotFound):
            await service.create_rule(uuid7(), "x", setup.measure.id, below(1), ["region"])


async def test_an_update_checks_the_revision_and_clears_what_may_be_empty(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup, check_interval_seconds=600)
    async with world.alerts() as service:
        updated = await service.update_rule(
            rule.id, 1, formula=below(60), key_columns=["region", "start"], enabled=False
        )
        with pytest.raises(Conflict):
            await service.update_rule(rule.id, 1, name="Stale")
        with pytest.raises(Invalid, match="max_data_age_seconds must be positive"):
            await service.update_rule(rule.id, 2, max_data_age_seconds=0)
    async with world.alerts() as service:
        cleared = await service.update_rule(rule.id, 2, check_interval_seconds=None)

    assert (updated.formula, updated.key_columns, updated.enabled) == (
        below(60),
        ("region", "start"),
        False,
    )
    # Left out: kept.
    assert (updated.check_interval_seconds, updated.name, updated.revision) == (600, rule.name, 2)
    assert (cleared.check_interval_seconds, cleared.key_columns, cleared.revision) == (
        None,
        ("region", "start"),
        3,
    )


async def test_a_check_opens_an_alert_per_alerting_key_on_the_rows_that_raised_it(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup)

    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
        rows = await service.rows(alert.id)
        stored = await service.get_rule(rule.id)

    assert alert.key == {"region": "north"}
    assert (alert.state, alert.started_at, alert.resolved_at) == (
        AlertState.FIRING,
        world.clock.now(),
        None,
    )
    assert alert.since_run_id == alert.last_run_id
    # The alert opens the exact rows that raised it: its condition over the measure.
    assert alert.condition_sql == compile_rule(rule.formula, MEASURE, rule.key_columns).sql
    assert [row[:1] + row[3:4] for row in rows.rows] == [("north", 70.0)]
    # The check is recorded outside the revision, so an edit from before does not conflict.
    assert (stored.last_checked_at, stored.revision) == (world.clock.now(), rule.revision)
    async with world.container() as request:
        run = await (await request.get(RunService)).get(alert.last_run_id)
    assert (run.started_by.kind, run.is_scenario) == ("system", False)


async def test_an_alert_stays_while_its_key_alerts_and_resolves_when_it_stops(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        (north,) = await service.check(rule.id)
    world.clock.advance(hours=1)
    async with world.alerts() as service:
        assert await service.check(rule.id) == []
        (kept,) = await service.alerts(setup.project_id)
    world.clock.advance(days=1)
    await world.refetch(
        setup.source,
        csv(("north", 2024, 70), ("north", 2025, 85), ("south", 2024, 92), ("south", 2025, 75)),
    )
    async with world.alerts() as service:
        changed = {alert.key["region"]: alert for alert in await service.check(rule.id)}
    world.clock.advance(days=1)
    await world.refetch(setup.source, START)
    async with world.alerts() as service:
        again = {alert.key["region"]: alert for alert in await service.check(rule.id)}

    assert (kept.id, kept.since_run_id, kept.started_at) == (
        north.id,
        north.since_run_id,
        north.started_at,
    )
    assert kept.last_run_id != north.last_run_id
    resolved = changed["north"]
    assert (resolved.id, resolved.state) == (north.id, AlertState.RESOLVED)
    # The last run that still showed the condition.
    assert resolved.last_run_id == kept.last_run_id
    assert changed["south"].state is AlertState.FIRING
    # A key that alerts again later gets a new alert.
    assert (again["north"].state, again["south"].state) == (
        AlertState.FIRING,
        AlertState.RESOLVED,
    )
    assert again["north"].id != north.id


async def test_events_go_out_after_the_check_commits_and_not_for_failed_work(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup)

    def alert_events(events: Sequence[Any]) -> list[Any]:
        return [e for e in events if e.type.value.startswith("alert.")]

    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
        assert alert_events(await world.events()) == []
    fired = alert_events(await world.events())
    # Data that would resolve the alert, checked in work that then fails.
    await world.refetch(setup.source, csv(("north", 2024, 90), ("south", 2024, 90)))
    with pytest.raises(RuntimeError):
        async with world.alerts() as service:
            assert await service.check(rule.id)
            raise RuntimeError("the request failed after the check")

    assert [(e.type, e.project_id, e.payload) for e in fired] == [
        (
            EventType.ALERT_FIRING,
            setup.project_id,
            {"alert_id": str(alert.id), "rule_id": str(rule.id)},
        )
    ]
    assert alert_events(await world.events()) == fired


async def test_a_rule_that_demands_fresher_data_has_it_refetched_or_checks_the_last_good(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup, max_data_age_seconds=3600)
    fetches = len(world.reader.fetches)
    async with world.alerts() as service:
        await service.check(rule.id)
    # Fetched just now: young enough, nothing is refetched.
    assert len(world.reader.fetches) == fetches

    world.clock.advance(hours=2)
    world.reader.content = csv(("north", 2024, 90), ("south", 2024, 60))
    async with world.alerts() as service:
        changed = await service.check(rule.id)
    assert len(world.reader.fetches) == fetches + 1
    assert {(a.key["region"], a.state) for a in changed} == {
        ("north", AlertState.RESOLVED),
        ("south", AlertState.FIRING),
    }

    world.clock.advance(hours=2)
    world.reader.content = ConnectionError("the source is down")
    async with world.alerts() as service:
        assert await service.check(rule.id) == []
    async with world.container() as request:
        source = await (await request.get(SourceService)).get(setup.source.id)
    assert source.last_error == "the source is down"


async def test_a_rule_is_due_when_its_interval_passed_or_its_data_changed(
    world: World, setup: Setup
) -> None:
    timed = await world.rule(setup, check_interval_seconds=600)
    on_change = await world.rule(setup, name="On change")
    disabled = await world.rule(setup, name="Off")
    async with world.alerts() as service:
        await service.update_rule(disabled.id, 1, enabled=False)

    async def due() -> list[UUID]:
        async with world.alerts() as service:
            return [r.id for r in await service.due()]

    # Never checked: due.
    assert await due() == [timed.id, on_change.id]
    async with world.alerts() as service:
        await service.check(timed.id)
        await service.check(on_change.id)
    world.clock.advance(seconds=599)
    assert await due() == []
    world.clock.advance(seconds=1)
    assert await due() == [timed.id]
    # The same content again makes no new snapshot; new content does.
    await world.refetch(setup.source, START)
    assert await due() == [timed.id]
    world.clock.advance(minutes=1)
    await world.refetch(setup.source, csv(("north", 2024, 90)))
    assert await due() == [timed.id, on_change.id]


async def test_pushed_snapshot_makes_alert_rule_due(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        await service.check(rule.id)
        assert await service.due() == []
    async with world.container() as request:
        sources = await request.get(SourceService)
        await sources.watch(setup.source.id)
        monitor_secret = "test-secret"

    body = b"{}"
    now = world.clock.now()
    signature = context_signature(monitor_secret, body, int(now.timestamp()))
    async with world.container() as request:
        assert await (await request.get(SourceService)).verify_push(
            setup.source.id, body, signature, now
        )
    # What the webhook queues: a forced refresh that finds new content.
    world.clock.advance(minutes=1)
    await world.refetch(setup.source, csv(("north", 2024, 90)))

    async with world.alerts() as service:
        assert [r.id for r in await service.due()] == [rule.id]


async def test_the_alert_pipeline_runs_on_the_alerting_rows_when_an_alert_fires(
    world: World, setup: Setup
) -> None:
    async with world.container() as request:
        pipelines = await request.get(PipelineService)
        columns = (
            Column(name="region", type=ColumnType.TEXT),
            Column(name="value", type=ColumnType.NUMBER),
        )
        slot = await pipelines.add_input(
            setup.project_id, "alerting", Schema(columns=columns), setup.measure.id, TESTER
        )
        summary = await pipelines.add_transform(
            setup.project_id, "SELECT count(*) AS regions FROM input_0", [slot.id], TESTER
        )
        plain = await pipelines.add_transform(setup.project_id, "SELECT 1 AS one", [], TESTER)
    with pytest.raises(Invalid, match="exactly one input"):
        await world.rule(setup, alert_pipeline_id=plain.id)
    rule = await world.rule(setup, alert_pipeline_id=summary.id)

    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
        # A check that opens nothing new does not run it again.
        await service.check(rule.id)

    finished = [
        e
        for e in await world.events()
        if e.type is EventType.RUN_FINISHED and e.payload["operator_id"] == summary.id
    ]
    assert len(finished) == 1
    run_id = UUID(finished[0].payload["run_id"])
    async with world.container() as request:
        repository = await request.get(RunRepository)
        run = await repository.get(run_id)
        check_run = await repository.get(alert.last_run_id)
        rows = await (await request.get(RunService)).read(run_id, summary.id)
    # The alert names the run of its pipeline, fed the alerting rows on the check's data.
    assert alert.pipeline_run_id == run_id
    assert check_run.snapshots.items() <= run.snapshots.items()
    assert rows.rows == ((1,),)


# REST: rules, checks and the feed


@pytest.fixture(scope="module")
def rest(unreachable_settings: Settings) -> Iterator[tuple[TestClient, World]]:
    overrides = AlertOverrides()
    app = create_app(unreachable_settings, *memory_adapters(), overrides)
    with TestClient(app) as client:
        container: AsyncContainer = client.app.state.dishka_container  # type: ignore[attr-defined]
        yield client, World(container, overrides)


@pytest.fixture
def rest_setup(rest: tuple[TestClient, World]) -> Setup:
    client, world = rest
    assert client.portal is not None
    return client.portal.call(world.setup, START)


def rule_body(setup: Setup, **changes: Any) -> dict[str, Any]:
    return {
        "name": "Coverage below target",
        "operator_id": setup.measure.id,
        "formula": below(80),
        "key_columns": ["region"],
    } | changes


BAD_FORMULA = {
    "id": "low",
    "kind": "compare",
    "op": "<",
    "args": [
        {"id": "where", "kind": "column", "column": "nowhere"},
        {"id": "limit", "kind": "constant", "value": 80},
    ],
}


def test_rules_are_created_and_patched_over_rest(
    rest: tuple[TestClient, World], rest_setup: Setup
) -> None:
    client, _ = rest
    url = f"/api/dashboards/{rest_setup.dashboard.id}/alert-rules"
    created = client.post(url, json=rule_body(rest_setup, check_interval_seconds=3600))
    rule = created.json()
    patch = f"/api/alert-rules/{rule['id']}"

    renamed = client.patch(patch, json={"expected_revision": 1, "name": "Too low"})
    stale = client.patch(patch, json={"expected_revision": 1})
    # Null clears; left out keeps.
    cleared = client.patch(patch, json={"expected_revision": 2, "check_interval_seconds": None})
    invalid = client.post(url, json=rule_body(rest_setup, formula=BAD_FORMULA))

    assert created.status_code == 201
    assert (renamed.json()["name"], renamed.json()["revision"]) == ("Too low", 2)
    assert stale.status_code == 409
    assert (stale.json()["expected_revision"], stale.json()["revision"]) == (1, 2)
    assert (cleared.json()["check_interval_seconds"], cleared.json()["name"]) == (None, "Too low")
    assert invalid.status_code == 422
    assert invalid.json()["detail"].startswith("Formula node 'where': 'nowhere' is not a column")
    grouped = client.get(f"/api/projects/{rest_setup.project_id}/alert-rules").json()
    assert [(g["dashboard"]["id"], [r["name"] for r in g["rules"]]) for g in grouped] == [
        (str(rest_setup.dashboard.id), ["Too low"])
    ]


def test_a_check_answers_with_the_changes_and_the_feed_lists_firing_alerts_first(
    rest: tuple[TestClient, World], rest_setup: Setup
) -> None:
    client, world = rest
    assert client.portal is not None
    rule = client.post(
        f"/api/dashboards/{rest_setup.dashboard.id}/alert-rules", json=rule_body(rest_setup)
    ).json()

    checked = client.post(f"/api/alert-rules/{rule['id']}/check").json()
    (alert,) = checked["changed"]
    rows = client.get(f"/api/alerts/{alert['id']}/rows").json()
    world.clock.advance(days=1)
    recovered = csv(("north", 2025, 90), ("south", 2025, 60))
    client.portal.call(world.refetch, rest_setup.source, recovered)
    client.post(f"/api/alert-rules/{rule['id']}/check")
    feed = client.get(f"/api/projects/{rest_setup.project_id}/alerts").json()

    assert (alert["key"], alert["state"], checked["firing"]) == (
        {"region": "north"},
        "firing",
        [alert],
    )
    # The alert opens the rows that raised it.
    assert [row[0] for row in rows["rows"]] == ["north"]
    assert [(v["alert"]["key"]["region"], v["alert"]["state"]) for v in feed] == [
        ("south", "firing"),
        ("north", "resolved"),
    ]
    assert client.get(f"/api/projects/{rest_setup.project_id}/alerts?state=burn").status_code == (
        422
    )


# MCP: the tools an agent sets rules with


@pytest.fixture(scope="module")
async def agent(unreachable_settings: Settings) -> AsyncIterator[tuple[Client, World]]:
    overrides = AlertOverrides()
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), overrides
    )
    try:
        async with Client(create_mcp(container)) as client:
            yield client, World(container, overrides)
    finally:
        await container.close()


async def test_an_agent_learns_the_formula_from_the_tool_and_sets_a_rule(
    agent: tuple[Client, World],
) -> None:
    client, world = agent
    tools = {tool.name: tool for tool in await client.list_tools()}
    description = tools["create_alert_rule"].description or ""
    # The formula format is in the tool's own description, with an example.
    for word in ("rolling_mean", "previous", "suppressed", '"kind": "compare"', "key_columns"):
        assert word in description
    setup = await world.setup(START)
    arguments = {
        "dashboard_id": str(setup.dashboard.id),
        "name": "Coverage below target",
        "operator_id": setup.measure.id,
        "key_columns": ["region"],
    }

    rule = await call(client, "create_alert_rule", **arguments, formula=below(80))
    checked = await call(client, "check_alert_rule", rule_id=rule["id"])
    feed = await call(client, "list_alerts", project_id=str(setup.project_id), state="firing")
    changed = await call(
        client,
        "update_alert_rule",
        rule_id=rule["id"],
        expected_revision=1,
        max_data_age_seconds=600,
        clear=["check_interval_seconds"],
    )

    (alert,) = checked["changed"]
    assert [(e["alert"]["id"], e["rule_name"]) for e in feed] == [
        (alert["id"], "Coverage below target")
    ]
    assert (changed["check_interval_seconds"], changed["max_data_age_seconds"]) == (None, 600)
    with pytest.raises(ToolError, match="Formula node 'where'"):
        await call(client, "create_alert_rule", **arguments, formula=BAD_FORMULA)


# PostgreSQL and the worker


async def test_alerts_fire_stay_and_resolve_on_postgresql(
    migrated_database_url: str, tmp_path: Path
) -> None:
    overrides = AlertOverrides()
    container = create_container(
        settings_in(tmp_path, migrated_database_url), MemoryBackground(), overrides
    )
    world = World(container, overrides)
    try:
        setup = await world.setup(csv(("north", 2024, 70), ("south", 2024, 90)))
        # A key of two columns, one of them a date, which JSONB stores as text.
        rule = await world.rule(setup, key_columns=["region", "start"])
        async with world.alerts() as service:
            (fired,) = await service.check(rule.id)
        world.clock.advance(hours=1)
        async with world.alerts() as service:
            assert await service.check(rule.id) == []
            edited = await service.update_rule(rule.id, rule.revision, enabled=False)
        world.clock.advance(days=1)
        # New data that recovers: the refetch supersedes the current snapshot before adding
        # the new one (uq_snapshots_current allows one).
        await world.refetch(setup.source, csv(("north", 2024, 85), ("south", 2024, 90)))
        async with world.alerts() as service:
            (resolved,) = await service.check(rule.id)
            assert await service.alerts(setup.project_id, AlertState.RESOLVED) == [resolved]
    finally:
        await container.close()

    assert fired.key == {"region": "north", "start": "2024-01-01"}
    assert edited.last_checked_at == world.clock.now() - timedelta(days=1)
    assert edited.revision == rule.revision + 1
    assert (resolved.id, resolved.resolved_at) == (fired.id, world.clock.now())


async def test_due_rules_are_queued_and_checked_by_the_worker(
    unreachable_settings: Settings,
) -> None:
    """The scheduled tick queues through the dispatcher the API uses, and the queued task
    checks the rule with the real services and announces the alert."""
    overrides = AlertOverrides()
    # A dispatcher that kicks the worker's own in-memory broker, bound before the broker
    # exists: the provider asks for it when a task first needs it.
    holder: dict[str, AsyncBroker] = {}
    background = Provider(scope=Scope.APP)
    background.provide(lambda: ValkeyTaskDispatcher(holder["broker"]), provides=TaskDispatcher)
    broker = create_broker(
        unreachable_settings, *memory_adapters(), overrides, background, in_memory=True
    )
    holder["broker"] = broker
    await broker.startup()
    try:
        middleware = next(m for m in broker.middlewares if isinstance(m, ContainerMiddleware))
        world = World(middleware._container, overrides)
        setup = await world.setup(csv(("north", 2024, 70), ("south", 2024, 90)))
        created = await world.rule(setup)
        task = broker.find_task("ada.entrypoints.worker.tasks.alerts:check_due_alert_rules")
        assert task is not None
        await (await task.kiq()).wait_result(timeout=5)
        await broker.wait_all()  # type: ignore[attr-defined]
        async with world.alerts() as alerts:
            (alert,) = await alerts.alerts(setup.project_id, AlertState.FIRING)
            assert (await alerts.get_rule(created.id)).last_checked_at == world.clock.now()
        assert EventType.ALERT_FIRING in [event.type for event in await world.events()]
    finally:
        await broker.shutdown()
    assert alert.key == {"region": "north"}
