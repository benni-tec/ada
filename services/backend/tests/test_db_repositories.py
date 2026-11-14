"""The expectations every repository implementation shares (docs/contracts.md), run
against the memory repositories, which are the reference, and the database ones.

Records are always stored under their parents: the database enforces what memory does not.
"""

from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import db_helpers
import factories
from ada.core.models.alerts import AlertState
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import OperatorKind
from ada.core.models.schema import GeoRole, Roles, Schema
from ada.core.models.sources import FreshnessKind, FreshnessPolicy
from ada.core.models.time import Interval, TimeRange
from db_helpers import Repos, make_world

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["memory", "database"])
async def repos(request: pytest.FixtureRequest) -> AsyncIterator[Repos]:
    if request.param == "memory":
        yield db_helpers.memory_repos()
        return
    url: str = request.getfixturevalue("migrated_database_url")
    async with db_helpers.engine_for(url) as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            yield db_helpers.sql_repos(session)


# Ported from test_memory_repositories.py ------------------------------------------------


async def test_get_of_an_unknown_id_is_not_found(repos: Repos) -> None:
    with pytest.raises(NotFound) as error:
        await repos.projects.get(factories.project().id)

    assert error.value.kind == "project"


async def test_update_increases_the_revision(repos: Repos) -> None:
    project = factories.project()
    await repos.projects.add(project)

    updated = await repos.projects.update(project.model_copy(update={"name": "Renamed"}), 1)

    assert (updated.name, updated.revision) == ("Renamed", 2)
    assert await repos.projects.get(project.id) == updated


async def test_update_with_a_stale_revision_conflicts_and_changes_nothing(repos: Repos) -> None:
    project = factories.project()
    await repos.projects.add(project)
    await repos.projects.update(project.model_copy(update={"name": "First"}), 1)

    with pytest.raises(Conflict) as error:
        await repos.projects.update(project.model_copy(update={"name": "Second"}), 1)

    assert (error.value.expected, error.value.actual) == (1, 2)
    assert (await repos.projects.get(project.id)).name == "First"


async def test_adding_the_same_operator_twice_keeps_the_first(repos: Repos) -> None:
    project = factories.project()
    await repos.projects.add(project)
    first = factories.operator(project.id)
    later = first.model_copy(update={"created_at": first.created_at + timedelta(days=1)})

    assert await repos.operators.add(first) == first
    assert await repos.operators.add(later) == first
    assert await repos.operators.list(project.id) == [first]


async def test_upstream_lists_inputs_before_what_uses_them(repos: Repos) -> None:
    world = await make_world(repos)
    project_id, source = world.project.id, world.source_operator
    left = factories.operator(
        project_id, params={"sql": "SELECT 1 FROM input_0"}, inputs=(source.id,)
    )
    right = factories.operator(
        project_id, params={"sql": "SELECT 2 FROM input_0"}, inputs=(source.id,)
    )
    joined = factories.operator(project_id, params={"sql": "join"}, inputs=(left.id, right.id))
    for operator in (left, right, joined):
        await repos.operators.add(operator)

    pipeline = [operator.id for operator in await repos.operators.upstream(joined.id)]

    # The shared source appears once, and the operator itself is last.
    assert pipeline == [source.id, left.id, right.id, joined.id]


async def test_reading_finds_the_source_operators_of_a_data_source(repos: Repos) -> None:
    world = await make_world(repos)
    other = factories.data_source(world.project.id)
    await repos.data_sources.add(other)

    assert await repos.operators.reading(world.source.id) == [world.source_operator]
    assert await repos.operators.reading(other.id) == []


async def test_a_superseded_snapshot_is_no_longer_current_but_stays_readable(
    repos: Repos,
) -> None:
    world = await make_world(repos)
    project_id, operator_id = world.project.id, world.operator.id
    old = factories.snapshot(project_id, operator_id, parameters_key="2024")
    await repos.snapshots.add(old)
    assert await repos.snapshots.current(operator_id, "2024") == old
    assert await repos.snapshots.current(operator_id, "2025") is None

    await repos.snapshots.supersede(old.id, factories.NOW)
    new = factories.snapshot(project_id, operator_id, parameters_key="2024", content_hash="def")
    await repos.snapshots.add(new)

    assert await repos.snapshots.current(operator_id, "2024") == new
    assert (await repos.snapshots.get(old.id)).superseded_at == factories.NOW


async def test_a_run_keeps_the_first_snapshot_it_fixed_for_an_operator(repos: Repos) -> None:
    world = await make_world(repos)
    operator_id = world.operator.id
    first = factories.snapshot(world.project.id, operator_id)
    second = factories.snapshot(world.project.id, operator_id, parameters_key="other")
    await repos.snapshots.add(first)
    await repos.snapshots.add(second)
    run = factories.run(world.project.id)
    await repos.runs.add(run)

    await repos.runs.fix_snapshot(run.id, operator_id, first.id)
    fixed = await repos.runs.fix_snapshot(run.id, operator_id, second.id)

    assert fixed.snapshots == {operator_id: first.id}
    assert (await repos.runs.get(run.id)).snapshots == {operator_id: first.id}


# Round trips and the rest of each port ---------------------------------------------------


async def test_every_get_of_an_unknown_id_names_its_kind(repos: Repos) -> None:
    unknown = factories.project().id
    cases = [
        (repos.data_sources.get(unknown), "data source"),
        (repos.sessions.get(unknown), "session"),
        (repos.operators.get("op_missing"), "operator"),
        (repos.snapshots.get(unknown), "snapshot"),
        (repos.runs.get(unknown), "run"),
        (repos.widgets.get(unknown), "widget"),
        (repos.dashboards.get(unknown), "dashboard"),
        (repos.dashboards.get_version(unknown), "dashboard version"),
        (repos.templates.get(unknown), "template"),
        (repos.reports.get(unknown), "report"),
        (repos.reports.get_version(unknown), "report version"),
        (repos.alert_rules.get(unknown), "alert rule"),
        (repos.alerts.get(unknown), "alert"),
    ]
    for call, kind in cases:
        with pytest.raises(NotFound) as error:
            await call
        assert error.value.kind == kind


async def test_projects_list_oldest_first(repos: Repos) -> None:
    older = factories.project(name="Older")
    newer = factories.project(name="Newer", created_at=factories.NOW + timedelta(days=1))
    await repos.projects.add(older)
    await repos.projects.add(newer)

    assert await repos.projects.list() == [older, newer]


async def test_a_data_source_round_trips_and_is_listed_by_project(repos: Repos) -> None:
    world = await make_world(repos)
    schema = Schema(
        columns=(factories.SCHEMA.columns[0],),
        roles=Roles(geo=GeoRole(code="region", system="sotkanet", level="county")),
    )
    source = factories.data_source(
        world.project.id,
        options={"method": "POST", "headers": {"accept": "text/csv"}, "rows_path": ["data"]},
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600),
        declared_schema=schema,
        last_error="boom",
    )
    other_project = factories.project()
    await repos.projects.add(other_project)
    elsewhere = factories.data_source(other_project.id)
    await repos.data_sources.add(source)
    await repos.data_sources.add(elsewhere)

    assert await repos.data_sources.get(source.id) == source
    assert await repos.data_sources.list(world.project.id) == [world.source, source]
    assert await repos.data_sources.list_all() == [world.source, source, elsewhere]


async def test_updating_a_data_source_changes_its_fields(repos: Repos) -> None:
    world = await make_world(repos)
    edited = world.source.model_copy(
        update={"name": "Renamed", "address": "https://example.test/other.csv"}
    )

    updated = await repos.data_sources.update(edited, 1)

    assert (updated.name, updated.revision) == ("Renamed", 2)
    assert await repos.data_sources.get(world.source.id) == updated


async def test_record_check_stores_the_outcome_and_keeps_the_revision(repos: Repos) -> None:
    world = await make_world(repos)
    at = factories.NOW + timedelta(hours=1)

    await repos.data_sources.record_check(world.source.id, at, "token", "timed out")

    stored = await repos.data_sources.get(world.source.id)
    assert (stored.last_checked_at, stored.last_probe_token, stored.last_error) == (
        at,
        "token",
        "timed out",
    )
    assert stored.revision == 1


async def test_a_session_and_its_entries_round_trip_in_order(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    session = factories.session(world.project.id, origin_dashboard_id=dashboard.id)
    await repos.sessions.add(session)
    later = db_helpers.entry(
        session.id, text="second", created_at=factories.NOW + timedelta(seconds=1)
    )
    first = db_helpers.entry(session.id, text="first")
    operator_entry = db_helpers.entry(
        session.id,
        kind="operator",
        ref=world.operator.id,
        created_at=factories.NOW + timedelta(seconds=2),
    )
    for entry in (first, later, operator_entry):
        await repos.sessions.add_entry(entry)

    assert await repos.sessions.get(session.id) == session
    assert await repos.sessions.list(world.project.id) == [session]
    assert await repos.sessions.entries(session.id) == [first, later, operator_entry]
    assert await repos.sessions.entries(factories.session(world.project.id).id) == []


async def test_updating_a_session_sets_the_panel_dashboard(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    session = factories.session(world.project.id)
    await repos.sessions.add(session)

    updated = await repos.sessions.update(
        session.model_copy(update={"title": "Renamed", "panel_dashboard_id": dashboard.id}), 1
    )

    assert (updated.title, updated.panel_dashboard_id, updated.revision) == (
        "Renamed",
        dashboard.id,
        2,
    )
    with pytest.raises(Conflict):
        await repos.sessions.update(session, 1)


async def test_an_entry_needs_its_session(repos: Repos) -> None:
    with pytest.raises(NotFound) as error:
        await repos.sessions.add_entry(
            db_helpers.entry(factories.session(factories.project().id).id)
        )

    assert error.value.kind == "session"


async def test_operators_round_trip_with_their_inputs_in_order(repos: Repos) -> None:
    world = await make_world(repos)
    project_id = world.project.id
    second_source = await repos.operators.add(
        factories.operator(
            project_id,
            OperatorKind.SOURCE,
            {"data_source_id": str(world.source.id), "extra": 1},
            output=Schema(derived=True),
        )
    )
    joined = factories.operator(
        project_id,
        params={"sql": "SELECT * FROM input_0 JOIN input_1"},
        inputs=(second_source.id, world.source_operator.id),
        materializing=True,
    )

    assert await repos.operators.add(joined) == joined

    assert await repos.operators.get(joined.id) == joined
    assert (await repos.operators.get(second_source.id)).output == Schema(derived=True)
    assert [o.id for o in await repos.operators.upstream(joined.id)] == [
        second_source.id,
        world.source_operator.id,
        joined.id,
    ]
    # Both source operators read the data source.
    assert {o.id for o in await repos.operators.reading(world.source.id)} == {
        world.source_operator.id,
        second_source.id,
    }


async def test_the_upstream_of_a_source_is_just_itself(repos: Repos) -> None:
    world = await make_world(repos)

    assert await repos.operators.upstream(world.source_operator.id) == [world.source_operator]


async def test_the_upstream_of_an_unknown_operator_is_not_found(repos: Repos) -> None:
    with pytest.raises(NotFound):
        await repos.operators.upstream("op_missing")


async def test_operators_are_listed_by_project(repos: Repos) -> None:
    world = await make_world(repos)
    other_project = factories.project()
    await repos.projects.add(other_project)
    await repos.operators.add(factories.operator(other_project.id))

    listed = await repos.operators.list(world.project.id)

    assert {o.id for o in listed} == {world.source_operator.id, world.operator.id}


async def test_snapshots_round_trip_and_are_listed_per_operator(repos: Repos) -> None:
    world = await make_world(repos)
    project_id, operator_id = world.project.id, world.source_operator.id
    first = factories.snapshot(
        project_id,
        operator_id,
        parameters_key="2023",
        period=Interval(start=date(2023, 1, 1), end=date(2023, 12, 31)),
        row_count=12,
    )
    second = factories.snapshot(
        project_id,
        operator_id,
        parameters_key="2024",
        fetched_at=factories.NOW + timedelta(days=1),
    )
    await repos.snapshots.add(first)
    await repos.snapshots.add(second)

    assert await repos.snapshots.get(first.id) == first
    assert await repos.snapshots.get(second.id) == second
    assert await repos.snapshots.list(operator_id) == [first, second]
    assert await repos.snapshots.list(world.operator.id) == []


async def test_runs_round_trip_with_their_fixed_snapshots(repos: Repos) -> None:
    world = await make_world(repos)
    snapshot = factories.snapshot(world.project.id, world.source_operator.id)
    await repos.snapshots.add(snapshot)
    run = factories.run(
        world.project.id,
        time_range=TimeRange(start=date(2022, 1, 1), end=date(2024, 12, 31)),
        bindings={"budget": world.operator.id},
        snapshots={world.source_operator.id: snapshot.id},
    )

    await repos.runs.add(run)

    stored = await repos.runs.get(run.id)
    assert stored == run
    assert stored.is_scenario


async def test_runs_list_newest_first_up_to_the_limit(repos: Repos) -> None:
    world = await make_world(repos)
    runs = [
        factories.run(world.project.id, started_at=factories.NOW + timedelta(minutes=minute))
        for minute in (5, 1, 3)
    ]
    for run in runs:
        await repos.runs.add(run)
    other_project = factories.project()
    await repos.projects.add(other_project)
    await repos.runs.add(factories.run(other_project.id))

    newest_first = await repos.runs.list(world.project.id)

    assert newest_first == [runs[0], runs[2], runs[1]]
    assert await repos.runs.list(world.project.id, limit=2) == [runs[0], runs[2]]


async def test_listed_runs_carry_their_snapshots(repos: Repos) -> None:
    world = await make_world(repos)
    snapshot = factories.snapshot(world.project.id, world.source_operator.id)
    await repos.snapshots.add(snapshot)
    run = factories.run(world.project.id)
    await repos.runs.add(run)
    await repos.runs.fix_snapshot(run.id, world.source_operator.id, snapshot.id)

    assert [r.snapshots for r in await repos.runs.list(world.project.id)] == [
        {world.source_operator.id: snapshot.id}
    ]


async def test_widgets_round_trip_and_are_listed_by_project_and_session(repos: Repos) -> None:
    world = await make_world(repos)
    session = factories.session(world.project.id)
    await repos.sessions.add(session)
    in_session = db_helpers.widget(world.project.id, world.operator.id, session_id=session.id)
    loose = db_helpers.widget(
        world.project.id, world.operator.id, created_at=factories.NOW + timedelta(seconds=1)
    )
    await repos.widgets.add(in_session)
    await repos.widgets.add(loose)

    assert await repos.widgets.get(in_session.id) == in_session
    assert await repos.widgets.list(world.project.id) == [in_session, loose]
    assert await repos.widgets.list_by_session(session.id) == [in_session]


async def test_dashboards_update_with_the_revision_check(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    assert await repos.dashboards.get(dashboard.id) == dashboard
    assert await repos.dashboards.list(world.project.id) == [dashboard]
    version = db_helpers.dashboard_version(dashboard.id, 1)
    await repos.dashboards.add_version(version)

    updated = await repos.dashboards.update(
        dashboard.model_copy(
            update={"current_version_id": version.id, "default_time_range": TimeRange()}
        ),
        1,
    )

    assert (updated.revision, updated.current_version_id) == (2, version.id)
    assert updated.default_time_range == TimeRange()
    assert await repos.dashboards.get(dashboard.id) == updated
    with pytest.raises(Conflict):
        await repos.dashboards.update(dashboard, 1)


async def test_dashboard_versions_are_immutable_records_listed_by_number(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    third = db_helpers.dashboard_version(dashboard.id, 3)
    first = db_helpers.dashboard_version(dashboard.id, 1)
    second = db_helpers.dashboard_version(dashboard.id, 2, slots=())
    for version in (third, first, second):
        await repos.dashboards.add_version(version)

    assert await repos.dashboards.get_version(first.id) == first
    assert await repos.dashboards.versions(dashboard.id) == [first, second, third]


async def test_a_version_needs_its_dashboard_and_its_report(repos: Repos) -> None:
    world = await make_world(repos)
    run = factories.run(world.project.id)
    await repos.runs.add(run)
    unknown = db_helpers.dashboard(world.project.id)
    with pytest.raises(NotFound) as dashboard_error:
        await repos.dashboards.add_version(db_helpers.dashboard_version(unknown.id, 1))
    with pytest.raises(NotFound) as report_error:
        await repos.reports.add_version(
            db_helpers.report_version(db_helpers.report(world.project.id).id, run.id)
        )

    assert dashboard_error.value.kind == "dashboard"
    assert report_error.value.kind == "report"


async def test_templates_round_trip_and_update(repos: Repos) -> None:
    world = await make_world(repos)
    template = db_helpers.template(world.project.id)
    await repos.templates.add(template)
    assert await repos.templates.get(template.id) == template
    assert await repos.templates.list(world.project.id) == [template]

    updated = await repos.templates.update(
        template.model_copy(update={"name": "Renamed", "slots": (), "content": {"type": "page"}}),
        1,
    )

    assert (updated.name, updated.revision, updated.slots) == ("Renamed", 2, ())
    assert await repos.templates.get(template.id) == updated
    with pytest.raises(Conflict):
        await repos.templates.update(template, 1)


async def test_reports_and_their_versions_round_trip(repos: Repos) -> None:
    world = await make_world(repos)
    session = factories.session(world.project.id)
    await repos.sessions.add(session)
    run = factories.run(world.project.id)
    await repos.runs.add(run)
    report = db_helpers.report(world.project.id, session_id=session.id)
    await repos.reports.add(report)
    first = db_helpers.report_version(report.id, run.id, "1.0.0")
    second = db_helpers.report_version(
        report.id, run.id, "1.1.0", created_at=factories.NOW + timedelta(days=1)
    )
    await repos.reports.add_version(first)
    await repos.reports.add_version(second)

    updated = await repos.reports.update(
        report.model_copy(update={"latest_version_id": second.id}), 1
    )

    assert await repos.reports.get(report.id) == updated
    assert updated.revision == 2
    assert await repos.reports.list(world.project.id) == [updated]
    assert await repos.reports.get_version(first.id) == first
    assert await repos.reports.versions(report.id) == [first, second]
    with pytest.raises(Conflict):
        await repos.reports.update(report, 1)


async def test_alert_rules_update_with_the_revision_check(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
    disabled = db_helpers.alert_rule(
        world.project.id,
        dashboard.id,
        world.operator.id,
        enabled=False,
        alert_pipeline_id=world.source_operator.id,
        created_at=factories.NOW + timedelta(seconds=1),
    )
    await repos.alert_rules.add(rule)
    await repos.alert_rules.add(disabled)
    assert await repos.alert_rules.get(rule.id) == rule
    assert await repos.alert_rules.list(dashboard.id) == [rule, disabled]
    assert await repos.alert_rules.list_enabled() == [rule]

    updated = await repos.alert_rules.update(
        rule.model_copy(update={"enabled": False, "key_columns": ("region", "indicator")}), 1
    )

    assert (updated.revision, updated.key_columns) == (2, ("region", "indicator"))
    assert await repos.alert_rules.list_enabled() == []
    with pytest.raises(Conflict):
        await repos.alert_rules.update(rule, 1)


async def test_a_rule_check_keeps_the_revision(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
    await repos.alert_rules.add(rule)
    at = factories.NOW + timedelta(hours=2)

    await repos.alert_rules.record_check(rule.id, at)

    assert await repos.alert_rules.get(rule.id) == rule.model_copy(update={"last_checked_at": at})


async def test_alerts_are_found_by_rule_and_key_only_while_firing(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
    await repos.alert_rules.add(rule)
    run = factories.run(world.project.id)
    await repos.runs.add(run)
    key = {"region": "Uusimaa", "indicator": 5}
    alert = db_helpers.alert(world.project.id, rule.id, run.id, key=key)
    await repos.alerts.add(alert)

    assert await repos.alerts.get(alert.id) == alert
    # The order of the key's members does not matter; its values do.
    assert await repos.alerts.find(rule.id, {"indicator": 5, "region": "Uusimaa"}) == alert
    assert await repos.alerts.find(rule.id, {"region": "Uusimaa", "indicator": 6}) is None
    assert await repos.alerts.find(rule.id, {"region": "Uusimaa"}) is None
    assert await repos.alerts.find(factories.project().id, key) is None

    resolved = alert.model_copy(
        update={"state": AlertState.RESOLVED, "resolved_at": factories.NOW + timedelta(days=1)}
    )
    await repos.alerts.save(resolved)

    assert await repos.alerts.get(alert.id) == resolved
    assert await repos.alerts.find(rule.id, key) is None


async def test_alerts_list_newest_first_and_by_state(repos: Repos) -> None:
    world = await make_world(repos)
    dashboard = db_helpers.dashboard(world.project.id)
    await repos.dashboards.add(dashboard)
    rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
    await repos.alert_rules.add(rule)
    run = factories.run(world.project.id)
    await repos.runs.add(run)
    old = db_helpers.alert(
        world.project.id, rule.id, run.id, key={"region": "A"}, state=AlertState.RESOLVED
    )
    new = db_helpers.alert(
        world.project.id,
        rule.id,
        run.id,
        key={"region": "B"},
        started_at=factories.NOW + timedelta(hours=1),
    )
    await repos.alerts.add(old)
    await repos.alerts.add(new)

    assert await repos.alerts.list(world.project.id) == [new, old]
    assert await repos.alerts.list(world.project.id, AlertState.FIRING) == [new]
    assert await repos.alerts.list(world.project.id, AlertState.RESOLVED) == [old]


async def test_saving_an_unknown_alert_is_not_found(repos: Repos) -> None:
    world = await make_world(repos)
    run = factories.run(world.project.id)

    with pytest.raises(NotFound):
        await repos.alerts.save(db_helpers.alert(world.project.id, run.id, run.id))
