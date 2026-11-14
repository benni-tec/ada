"""AlertService over the real pipeline, run and source services, DuckDB in tmp_path and the
memory repositories: rules, checks that fire, keep and resolve alerts, events after the
commit, data age, due rules and alert pipelines."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid7

import pytest

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertRule, AlertState, Severity
from ada.core.models.errors import Conflict, Invalid, NotFound
from ada.core.models.events import EventType
from ada.core.models.operators import OperatorKind, operator_identity
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.ports.repositories import OperatorRepository, RunRepository
from ada.core.services.alerts import service as alert_service
from ada.core.services.alerts.formula import compile_rule
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService
from alerts_support import MEASURE, TESTER, AlertOverrides, Setup, World, below, csv
from memory import memory_adapters

pytestmark = pytest.mark.anyio

START = csv(("north", 2023, 85), ("north", 2024, 70), ("south", 2023, 90), ("south", 2024, 92))


@pytest.fixture
async def world(unreachable_settings: Settings) -> AsyncIterator[World]:
    overrides = AlertOverrides()
    container = create_container(unreachable_settings, *memory_adapters(), overrides)
    try:
        yield World(container, overrides)
    finally:
        await container.close()


@pytest.fixture
async def setup(world: World) -> Setup:
    return await world.setup(START)


def alerting_operator_id(setup: Setup, rule: AlertRule) -> str:
    compiled = compile_rule(rule.formula, setup.measure.output, rule.key_columns)
    return operator_identity(
        setup.project_id, OperatorKind.TRANSFORM, {"sql": compiled.sql}, (setup.measure.id,)
    )


# Rules


async def test_a_rule_is_created_with_its_alerting_operator(world: World, setup: Setup) -> None:
    rule = await world.rule(setup, severity=Severity.CRITICAL, check_interval_seconds=3600)
    assert rule.project_id == setup.project_id
    assert rule.dashboard_id == setup.dashboard.id
    assert rule.key_columns == ("region",)
    assert rule.severity is Severity.CRITICAL
    assert rule.revision == 1
    assert rule.last_checked_at is None
    async with world.alerts() as service:
        assert await service.get_rule(rule.id) == rule
        assert await service.list_rules(setup.dashboard.id) == [rule]
    # The condition is a transform over the measure, in the lineage like any other step.
    async with world.container() as request:
        alerting = await (await request.get(OperatorRepository)).get(
            alerting_operator_id(setup, rule)
        )
    assert alerting.inputs == (setup.measure.id,)
    assert alerting.created_by.kind == "system"
    assert [c.name for c in alerting.output.columns] == [c.name for c in MEASURE.columns]
    assert alerting.output.roles == MEASURE.roles


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "formula": below(80)
                | {
                    "args": [
                        {"id": "x", "kind": "column", "column": "nope"},
                        {"id": "c", "kind": "constant", "value": 1},
                    ]
                }
            },
            "Formula node 'x'",
        ),
        ({"key_columns": ["nope"]}, "key column 'nope'"),
        ({"operator_id": "op_missing"}, "does not exist"),
        ({"name": "  "}, "needs a name"),
        ({"check_interval_seconds": 0}, "check_interval_seconds must be positive"),
        ({"max_data_age_seconds": -1}, "max_data_age_seconds must be positive"),
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


async def test_a_rule_needs_an_existing_dashboard_and_a_measure_of_its_project(
    world: World, setup: Setup
) -> None:
    async with world.alerts() as service:
        with pytest.raises(NotFound):
            await service.create_rule(uuid7(), "x", setup.measure.id, below(1), ["region"])
    other = await world.setup(START)
    with pytest.raises(Invalid, match="belongs to another project"):
        await world.rule(setup, operator_id=other.measure.id)


async def test_a_measure_without_columns_is_refused(world: World, setup: Setup) -> None:
    async with world.container() as request:
        operators = await request.get(OperatorRepository)
        (source_operator,) = await operators.reading(setup.source.id)
    # Registered with a declared schema, so the source operator has columns; an
    # undeclared one would not. Check the message by asking for a rule on a fake.
    assert source_operator.output.columns
    bare = source_operator.model_copy(
        update={"id": "op_bare", "output": Schema(), "params": {"data_source_id": str(uuid7())}}
    )
    async with world.container() as request:
        await (await request.get(OperatorRepository)).add(bare)
    with pytest.raises(Invalid, match="are not declared"):
        await world.rule(setup, operator_id="op_bare")


async def test_rules_are_updated_with_a_revision_check(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        updated = await service.update_rule(
            rule.id, 1, name="Too low", formula=below(60), severity=Severity.INFO, enabled=False
        )
    assert (updated.name, updated.formula, updated.severity, updated.enabled) == (
        "Too low",
        below(60),
        Severity.INFO,
        False,
    )
    assert updated.revision == 2
    assert updated.check_interval_seconds is None
    async with world.alerts() as service:
        with pytest.raises(Conflict):
            await service.update_rule(rule.id, 1, name="Stale")
        with pytest.raises(Invalid, match="Formula node 'low': cannot compare a text"):
            bad = below(60) | {
                "args": [
                    {"id": "value", "kind": "column", "column": "region"},
                    {"id": "c", "kind": "constant", "value": 1},
                ]
            }
            await service.update_rule(rule.id, 2, formula=bad)
        assert (await service.get_rule(rule.id)).revision == 2


# Checks


async def test_a_check_opens_an_alert_per_alerting_key(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        changed = await service.check(rule.id)
    (alert,) = changed
    assert alert.key == {"region": "north"}
    assert alert.state is AlertState.FIRING
    assert alert.since_run_id == alert.last_run_id
    assert alert.started_at == world.clock.now()
    assert alert.resolved_at is None

    # The alert opens the exact rows that raised it: the alerting operator in its run.
    async with world.container() as request:
        runs = await request.get(RunService)
        rows = await runs.read(alert.last_run_id, alerting_operator_id(setup, rule))
        run = await runs.get(alert.last_run_id)
    assert [row[:1] + row[3:4] for row in rows.rows] == [("north", 70.0)]
    assert run.started_by.kind == "system"
    assert not run.is_scenario

    async with world.alerts() as service:
        assert await service.alerts(setup.project_id) == [alert]
        assert await service.alerts(setup.project_id, AlertState.FIRING) == [alert]
        assert await service.alerts(setup.project_id, AlertState.RESOLVED) == []


async def test_a_key_that_keeps_alerting_keeps_its_alert(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        (first,) = await service.check(rule.id)
    world.clock.advance(hours=1)
    async with world.alerts() as service:
        assert await service.check(rule.id) == []
        (kept,) = await service.alerts(setup.project_id)
    assert kept.id == first.id
    assert kept.since_run_id == first.since_run_id
    assert kept.last_run_id != first.last_run_id
    assert kept.started_at == first.started_at


async def test_keys_that_stop_alerting_are_resolved(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        (north,) = await service.check(rule.id)
    world.clock.advance(days=1)
    await world.refetch(
        setup.source,
        csv(("north", 2024, 70), ("north", 2025, 85), ("south", 2024, 92), ("south", 2025, 75)),
    )
    async with world.alerts() as service:
        changed = await service.check(rule.id)
        feed = await service.alerts(setup.project_id)
    by_key = {alert.key["region"]: alert for alert in changed}
    assert set(by_key) == {"north", "south"}
    resolved, south = by_key["north"], by_key["south"]
    assert resolved.id == north.id
    assert resolved.state is AlertState.RESOLVED
    assert resolved.resolved_at == world.clock.now()
    # The last run that still showed the condition.
    assert resolved.last_run_id == north.last_run_id
    assert south.state is AlertState.FIRING
    assert south.since_run_id != north.since_run_id
    assert {alert.id for alert in feed} == {north.id, south.id}
    # A key that alerts again later gets a new alert.
    world.clock.advance(days=1)
    await world.refetch(setup.source, START)
    async with world.alerts() as service:
        changed = await service.check(rule.id)
    assert {(a.key["region"], a.state) for a in changed} == {
        ("north", AlertState.FIRING),
        ("south", AlertState.RESOLVED),
    }
    assert next(a for a in changed if a.key["region"] == "north").id != north.id


async def test_events_go_out_after_the_check_commits(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
        alert_events = [e for e in await world.events() if e.type.value.startswith("alert.")]
        assert alert_events == []
    events = [e for e in await world.events() if e.type is EventType.ALERT_FIRING]
    assert [(e.project_id, e.payload) for e in events] == [
        (setup.project_id, {"alert_id": str(alert.id), "rule_id": str(rule.id)})
    ]

    await world.refetch(setup.source, csv(("north", 2024, 90), ("south", 2024, 90)))
    async with world.alerts() as service:
        await service.check(rule.id)
    resolved = [e for e in await world.events() if e.type is EventType.ALERT_RESOLVED]
    assert [e.payload for e in resolved] == [{"alert_id": str(alert.id), "rule_id": str(rule.id)}]


async def test_a_failed_unit_of_work_announces_nothing(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    with pytest.raises(RuntimeError):
        async with world.alerts() as service:
            await service.check(rule.id)
            raise RuntimeError("the request failed after the check")
    assert [e for e in await world.events() if e.type.value.startswith("alert.")] == []


async def test_suppressed_values_never_alert(world: World, setup: Setup) -> None:
    await world.refetch(setup.source, csv(("north", 2023, 90), ("north", 2024, None)))
    rule = await world.rule(setup)
    async with world.alerts() as service:
        assert await service.check(rule.id) == []


async def test_time_functions_compare_with_the_previous_period(world: World, setup: Setup) -> None:
    dropped = {
        "id": "drop",
        "kind": "compare",
        "op": "<=",
        "args": [
            {
                "id": "change",
                "kind": "change",
                "periods": 1,
                "args": [{"id": "value", "kind": "column", "column": "value"}],
            },
            {"id": "five", "kind": "constant", "value": -5},
        ],
    }
    rule = await world.rule(setup, formula=dropped)
    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
    # north fell from 85 to 70; south rose.
    assert alert.key == {"region": "north"}


async def test_a_check_records_its_start_outside_the_revision(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    checked_at = world.clock.now()
    async with world.alerts() as service:
        await service.check(rule.id)
        after = await service.get_rule(rule.id)
    assert after.last_checked_at == checked_at
    assert after.revision == rule.revision
    # An edit made from the rule as read before the check does not conflict with it.
    async with world.alerts() as service:
        edited = await service.update_rule(rule.id, rule.revision, name="Renamed")
    assert edited.last_checked_at == checked_at


async def test_too_many_alerting_keys_fail_the_check(
    world: World, setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alert_service, "MAX_ALERTING_ROWS", 1)
    rule = await world.rule(setup, formula=below(100))
    async with world.alerts() as service:
        with pytest.raises(Invalid, match="More than 1 rows alert"):
            await service.check(rule.id)
        assert await service.alerts(setup.project_id) == []


# Data age


async def test_old_data_is_refetched_for_a_rule_that_demands_fresher(
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

    # A refetch that finds the same content writes no snapshot, but confirms the data.
    world.clock.advance(minutes=30)
    async with world.alerts() as service:
        await service.check(rule.id)
    assert len(world.reader.fetches) == fetches + 1


async def test_without_a_maximum_age_the_sources_policy_decides(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    fetches = len(world.reader.fetches)
    world.clock.advance(days=30)
    async with world.alerts() as service:
        await service.check(rule.id)
    # The source's policy is manual: a run never refetches it.
    assert len(world.reader.fetches) == fetches


async def test_a_failed_forced_refresh_checks_the_last_good_data(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup, max_data_age_seconds=60)
    world.clock.advance(hours=1)
    world.reader.content = ConnectionError("the source is down")
    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
    assert alert.key == {"region": "north"}
    async with world.container() as request:
        source = await (await request.get(SourceService)).get(setup.source.id)
    assert source.last_error == "the source is down"


# Due rules


async def test_a_rule_never_checked_is_due(world: World, setup: Setup) -> None:
    rule = await world.rule(setup, check_interval_seconds=600)
    async with world.alerts() as service:
        assert [r.id for r in await service.due()] == [rule.id]


async def test_a_rule_with_an_interval_is_due_when_it_has_passed(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup, check_interval_seconds=600)
    async with world.alerts() as service:
        await service.check(rule.id)
        assert await service.due() == []
    world.clock.advance(seconds=599)
    async with world.alerts() as service:
        assert await service.due() == []
    world.clock.advance(seconds=1)
    async with world.alerts() as service:
        assert [r.id for r in await service.due()] == [rule.id]


async def test_a_rule_without_an_interval_is_due_when_its_data_changed(
    world: World, setup: Setup
) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        await service.check(rule.id)
    world.clock.advance(days=1)
    async with world.alerts() as service:
        assert await service.due() == []
    # The same content again: no new snapshot, nothing to check.
    await world.refetch(setup.source, START)
    async with world.alerts() as service:
        assert await service.due() == []
    world.clock.advance(minutes=1)
    await world.refetch(setup.source, csv(("north", 2024, 90)))
    async with world.alerts() as service:
        assert [r.id for r in await service.due()] == [rule.id]
        await service.check(rule.id)
        assert await service.due() == []


async def test_disabled_rules_are_never_due(world: World, setup: Setup) -> None:
    rule = await world.rule(setup)
    async with world.alerts() as service:
        await service.update_rule(rule.id, 1, enabled=False)
        assert await service.due() == []


# Alert pipelines


async def alert_pipeline(world: World, setup: Setup) -> str:
    """An input slot for the alerting rows and a count over it."""
    async with world.container() as request:
        pipelines = await request.get(PipelineService)
        slot = await pipelines.add_input(
            setup.project_id,
            "alerting",
            Schema(
                columns=(
                    Column(name="region", type=ColumnType.TEXT),
                    Column(name="value", type=ColumnType.NUMBER),
                )
            ),
            setup.measure.id,
            TESTER,
        )
        summary = await pipelines.add_transform(
            setup.project_id, "SELECT count(*) AS regions FROM input_0", [slot.id], TESTER
        )
    return summary.id


async def test_the_alert_pipeline_runs_on_the_alerting_rows_when_an_alert_fires(
    world: World, setup: Setup
) -> None:
    pipeline_id = await alert_pipeline(world, setup)
    rule = await world.rule(setup, alert_pipeline_id=pipeline_id)
    async with world.alerts() as service:
        (alert,) = await service.check(rule.id)
    finished = [
        e
        for e in await world.events()
        if e.type is EventType.RUN_FINISHED and e.payload["operator_id"] == pipeline_id
    ]
    assert len(finished) == 1
    async with world.container() as request:
        runs = await request.get(RunService)
        repository = await request.get(RunRepository)
        run_id = UUID(finished[0].payload["run_id"])
        run = await repository.get(run_id)
        check_run = await repository.get(alert.last_run_id)
        rows = await runs.read(run_id, pipeline_id)
    # Bound to the alerting rows, on the same data as the check.
    assert run.bindings == {"alerting": alerting_operator_id(setup, rule)}
    assert check_run.snapshots.items() <= run.snapshots.items()
    assert rows.rows == ((1,),)

    # A check that opens nothing new does not run it again.
    async with world.alerts() as service:
        await service.check(rule.id)
    again = [
        e
        for e in await world.events()
        if e.type is EventType.RUN_FINISHED and e.payload["operator_id"] == pipeline_id
    ]
    assert len(again) == 1


async def test_an_alert_pipeline_needs_one_fitting_input(world: World, setup: Setup) -> None:
    async with world.container() as request:
        pipelines = await request.get(PipelineService)
        plain = await pipelines.add_transform(setup.project_id, "SELECT 1 AS one", [], TESTER)
        slot = await pipelines.add_input(
            setup.project_id,
            "other",
            Schema(columns=(Column(name="one", type=ColumnType.INTEGER),)),
            plain.id,
            TESTER,
        )
    with pytest.raises(Invalid, match="exactly one input"):
        await world.rule(setup, alert_pipeline_id=plain.id)
    with pytest.raises(Invalid, match="input 'other': 'one' is missing"):
        await world.rule(setup, alert_pipeline_id=slot.id)
