"""PostgreSQL: the migrations, transactions and concurrent writers, and the queries of the
SQL repositories that are easy to get wrong. The services' own tests run on the memory
repositories; what only the database has to get right is here."""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

import db_helpers
import factories
from ada.adapters.db.agent_repositories import SqlTurnProgress
from ada.adapters.db.base import Base
from ada.adapters.db.migrate import _config, migrate
from ada.composition import create_container
from ada.core.models.agents import (
    AgentTurn,
    ReasoningPart,
    SourcePart,
    TextPart,
    ToolPart,
    ToolState,
    TurnStatus,
)
from ada.core.models.alerts import AlertState
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import OperatorKind
from ada.core.models.schema import GeoRole, Roles, Schema
from ada.core.models.sessions import DashboardContext, PipelineContext, SessionAgent
from ada.core.models.sources import FoundBy, FreshnessKind, FreshnessPolicy, Provenance
from ada.core.models.time import Interval, TimeRange
from ada.core.ports.repositories import ProjectRepository
from conftest import settings_in
from db_helpers import Repos, engine_for, make_world, unit_of_work
from memory import MemoryBackground

pytestmark = pytest.mark.anyio


# Migrations


def test_migrations_build_every_table_and_can_be_undone(database_url: str) -> None:
    assert migrate(database_url) == ["0001", "0002", "0003", "0004", "0005", "0006"]
    engine = create_engine(database_url)
    try:
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        # 0005 adds the agent configuration with its one settings row.
        with engine.connect() as connection:
            settings = connection.exec_driver_sql(
                "SELECT id, session_agent_model_id, revision FROM agent_settings"
            ).all()
        assert [tuple(row) for row in settings] == [(1, None, 1)]

        command.downgrade(_config(database_url), "0001")

        inspector = inspect(engine)
        assert "agent_turns" not in inspector.get_table_names()
        assert "condition_sql" not in {c["name"] for c in inspector.get_columns("alerts")}
        assert "agent_settings" not in inspector.get_table_names()
    finally:
        engine.dispose()
    assert migrate(database_url) == ["0002", "0003", "0004", "0005", "0006"]
    assert migrate(database_url) == []


def test_migration_0006_keeps_existing_rows(database_url: str) -> None:
    config = _config(database_url)
    command.upgrade(config, "0005")
    project, source, session = uuid7(), uuid7(), uuid7()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, created_at, revision) VALUES (:p, 'P',"
                    " now(), 1)"
                ),
                {"p": project},
            )
            connection.execute(
                text(
                    "INSERT INTO data_sources (id, project_id, name, access_kind, address, format,"
                    " options, freshness, created_at, revision) VALUES (:s, :p, 'S', 'url', 'u',"
                    " 'csv', '{}', '{}', now(), 1)"
                ),
                {"s": source, "p": project},
            )
            connection.execute(
                text(
                    "INSERT INTO sessions (id, project_id, title, created_at, revision)"
                    " VALUES (:s, :p, 'T', now(), 1)"
                ),
                {"s": session, "p": project},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            source_row = connection.execute(
                text("SELECT provenance, monitor_id, monitor_secret_encrypted FROM data_sources")
            ).one()
            session_row = connection.execute(
                text("SELECT agent, parent_session_id, web_calls FROM sessions")
            ).one()
            settings = connection.execute(
                text("SELECT research_agent_model_id FROM agent_settings")
            ).one()
        assert tuple(source_row) == (None, None, None)
        assert tuple(session_row) == ("session", None, 0)
        assert tuple(settings) == (None,)
    finally:
        engine.dispose()


def test_the_tables_in_code_match_the_migrations(migrated_database_url: str) -> None:
    # Fails when a table was changed without writing a migration for it.
    command.check(_config(migrated_database_url))


# Units of work and revisions


@pytest.fixture
async def engine(migrated_database_url: str):  # noqa: ANN201
    async with engine_for(migrated_database_url) as engine:
        yield engine


async def scalar(engine: AsyncEngine, statement: str, **parameters: object) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(statement), parameters)).scalar_one()


async def test_a_request_commits_when_it_ends_and_rolls_back_when_it_raises(
    migrated_database_url: str, tmp_path: Path
) -> None:
    container = create_container(settings_in(tmp_path, migrated_database_url), MemoryBackground())
    try:
        with pytest.raises(RuntimeError):
            async with container() as request:
                await (await request.get(ProjectRepository)).add(factories.project())
                raise RuntimeError("boom")
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
        async with container() as request:
            assert await (await request.get(ProjectRepository)).list() == [project]
    finally:
        await container.close()


async def test_a_write_from_a_stale_read_conflicts_across_requests(engine: AsyncEngine) -> None:
    project = factories.project(revision=7)
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)
    async with unit_of_work(engine) as reader:
        read = await reader.projects.get(project.id)
        # A new record starts at revision one, whatever the model says.
        assert read.revision == 1
        async with unit_of_work(engine) as other:
            await other.projects.update(read.model_copy(update={"name": "Theirs"}), 1)

        with pytest.raises(Conflict) as error:
            await reader.projects.update(read.model_copy(update={"name": "Mine"}), 1)

    assert (error.value.kind, error.value.id) == ("project", project.id)
    assert (error.value.expected, error.value.actual) == (1, 2)
    async with unit_of_work(engine) as repos:
        stored = await repos.projects.get(project.id)
        with pytest.raises(NotFound):
            await repos.projects.update(factories.project(), 1)
    assert (stored.name, stored.revision) == ("Theirs", 2)


async def test_two_writers_racing_from_the_same_revision_cannot_both_win(
    engine: AsyncEngine,
) -> None:
    project = factories.project()
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)

    async def rename(name: str) -> str:
        try:
            async with unit_of_work(engine) as repos:
                await repos.projects.update(project.model_copy(update={"name": name}), 1)
        except Conflict:
            return "conflict"
        return "updated"

    outcomes = await asyncio.gather(*(rename(f"Writer {n}") for n in range(5)))

    assert sorted(outcomes) == ["conflict"] * 4 + ["updated"]
    async with unit_of_work(engine) as repos:
        assert (await repos.projects.get(project.id)).revision == 2


async def test_a_check_is_recorded_without_a_revision_and_an_edit_does_not_undo_it(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(dashboard)
        rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
        await repos.alert_rules.add(rule)
    async with unit_of_work(engine) as repos:
        read = await repos.data_sources.get(world.source.id)
    at = factories.NOW + timedelta(hours=1)
    async with unit_of_work(engine) as repos:
        await repos.data_sources.record_check(world.source.id, at, "token", "timed out")
        await repos.alert_rules.record_check(rule.id, at)
        # Both objects are in the session's memory now; the writes above bypassed it.
        assert (await repos.data_sources.get(world.source.id)).last_error == "timed out"
    assert await scalar(engine, "SELECT revision FROM data_sources") == 1
    assert await scalar(engine, "SELECT revision FROM alert_rules") == 1

    async with unit_of_work(engine) as repos:
        # The edits read the records before the checks, and must not undo their outcome.
        source = await repos.data_sources.update(read.model_copy(update={"name": "Edited"}), 1)
        edited = await repos.alert_rules.update(rule.model_copy(update={"name": "Edited"}), 1)
        with pytest.raises(NotFound):
            await repos.data_sources.record_check(uuid7(), at, None, None)

    assert (source.name, source.last_checked_at, source.last_error, source.revision) == (
        "Edited",
        at,
        "timed out",
        2,
    )
    assert (edited.last_checked_at, edited.revision) == (at, 2)


async def test_times_come_back_aware_and_lists_follow_creation_time(engine: AsyncEngine) -> None:
    helsinki = timezone(timedelta(hours=2))
    newer = factories.project(created_at=datetime(2026, 3, 1, 9, 30, tzinfo=helsinki))
    older = factories.project(created_at=factories.NOW)
    async with unit_of_work(engine) as repos:
        await repos.projects.add(newer)
        await repos.projects.add(older)

    async with unit_of_work(engine) as repos:
        listed = await repos.projects.list()

    assert listed == [older, newer]
    assert listed[1].created_at.tzinfo is not None
    assert listed[1].created_at.astimezone(UTC) == datetime(2026, 3, 1, 7, 30, tzinfo=UTC)


async def test_every_get_of_an_unknown_id_names_its_kind(engine: AsyncEngine) -> None:
    unknown = uuid7()
    async with unit_of_work(engine) as repos:
        cases = [
            (repos.projects.get(unknown), "project"),
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
            (repos.agent_turns.get(unknown), "agent turn"),
        ]
        for call, kind in cases:
            with pytest.raises(NotFound) as error:
                await call
            assert error.value.kind == kind


# Round trips: every field of every record comes back as it went in.


async def test_workspace_records_round_trip(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        source = factories.data_source(
            world.project.id,
            options={"method": "POST", "headers": {"accept": "text/csv"}, "rows_path": ["data"]},
            freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600),
            declared_schema=Schema(
                columns=(factories.SCHEMA.columns[0],),
                roles=Roles(geo=GeoRole(code="region", system="sotkanet", level="county")),
            ),
            last_error="boom",
            provenance=Provenance(
                publisher="THL",
                licence="unknown",
                found_by=FoundBy(query="stroke survival", scope="web"),
                extracted_by_model=True,
            ),
        )
        await repos.data_sources.add(source)
        dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(dashboard)
        session = factories.session(world.project.id, origin_dashboard_id=dashboard.id)
        await repos.sessions.add(session)
        child = factories.session(
            world.project.id, agent=SessionAgent.RESEARCH, parent_session_id=session.id
        )
        await repos.sessions.add(child)
        later = db_helpers.entry(session.id, created_at=factories.NOW + timedelta(seconds=1))
        first = db_helpers.entry(
            session.id,
            context=(
                PipelineContext(operator_id=world.operator.id),
                DashboardContext(dashboard_id=dashboard.id, slot="headline"),
            ),
        )
        await repos.sessions.add_entry(later)
        await repos.sessions.add_entry(first)
        original = db_helpers.widget(world.project.id, world.operator.id, session_id=session.id)
        copy = db_helpers.widget(
            world.project.id,
            world.operator.id,
            copied_from=original.id,
            created_at=factories.NOW + timedelta(seconds=1),
        )
        await repos.widgets.add(original)
        await repos.widgets.add(copy)
        with pytest.raises(NotFound):
            await repos.sessions.add_entry(db_helpers.entry(uuid7()))

    async with unit_of_work(engine) as repos:
        assert await repos.data_sources.list(world.project.id) == [world.source, source]
        assert await repos.sessions.get(session.id) == session
        assert await repos.sessions.get(child.id) == child
        assert [await repos.sessions.use_web_call(child.id, 2) for _ in range(3)] == [
            True,
            True,
            False,
        ]
        # A monitor is written outside the revision; its secret never leaves the repository.
        await repos.data_sources.set_monitor(source.id, "mon_1", "sealed")
        watched = await repos.data_sources.get(source.id)
        assert (watched.monitor_id, watched.revision) == ("mon_1", 1)
        assert await repos.data_sources.monitor_secret_encrypted(source.id) == "sealed"
        assert "sealed" not in watched.model_dump_json()
        await repos.data_sources.set_monitor(source.id, None, None)
        assert await repos.data_sources.monitor_secret_encrypted(source.id) is None
        assert await repos.sessions.entries(session.id) == [first, later]
        assert await repos.widgets.list(world.project.id) == [original, copy]
        assert await repos.widgets.list_by_session(session.id) == [original]
        updated = await repos.sessions.update(
            session.model_copy(update={"panel_dashboard_id": dashboard.id}), 1
        )
    assert (updated.panel_dashboard_id, updated.revision) == (dashboard.id, 2)


async def test_reporting_records_round_trip(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(dashboard)
        versions = [db_helpers.dashboard_version(dashboard.id, n) for n in (2, 1)]
        for version in versions:
            await repos.dashboards.add_version(version)
        template = db_helpers.template(world.project.id)
        await repos.templates.add(template)
        run = factories.run(world.project.id)
        await repos.runs.add(run)
        report = db_helpers.report(world.project.id, dashboard_id=dashboard.id)
        await repos.reports.add(report)
        report_versions = [
            db_helpers.report_version(report.id, run.id, "1.0.0"),
            db_helpers.report_version(
                report.id, run.id, "1.1.0", created_at=factories.NOW + timedelta(days=1)
            ),
        ]
        for version in report_versions:
            await repos.reports.add_version(version)
        with pytest.raises(NotFound) as error:
            await repos.dashboards.add_version(db_helpers.dashboard_version(uuid7(), 1))
        assert error.value.kind == "dashboard"

    async with unit_of_work(engine) as repos:
        assert await repos.dashboards.versions(dashboard.id) == versions[::-1]
        moved = await repos.dashboards.update(
            dashboard.model_copy(
                update={"current_version_id": versions[0].id, "default_time_range": TimeRange()}
            ),
            1,
        )
        assert await repos.templates.list(world.project.id) == [template]
        assert await repos.reports.versions(report.id) == report_versions
        latest = await repos.reports.update(
            report.model_copy(update={"latest_version_id": report_versions[1].id}), 1
        )
        with pytest.raises(Conflict):
            await repos.reports.update(report, 1)
    async with unit_of_work(engine) as repos:
        assert await repos.dashboards.get(dashboard.id) == moved
        assert await repos.reports.list(world.project.id) == [latest]


async def test_alert_rules_and_alerts_round_trip(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
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

    async with unit_of_work(engine) as repos:
        assert await repos.alert_rules.list(dashboard.id) == [rule, disabled]
        assert await repos.alert_rules.list_enabled() == [rule]
        assert await repos.alerts.list(world.project.id) == [new, old]
        assert await repos.alerts.list(world.project.id, AlertState.FIRING) == [new]
        with pytest.raises(NotFound):
            await repos.alerts.save(db_helpers.alert(world.project.id, run.id, run.id))


async def test_an_alert_is_found_by_its_exact_key_only_while_firing(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(dashboard)
        rules = [
            db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
            for _ in range(2)
        ]
        for rule in rules:
            await repos.alert_rules.add(rule)
        run = factories.run(world.project.id)
        await repos.runs.add(run)
        # A key that holds nested values and nulls.
        key = {"region": "A", "tags": ["x", {"y": None}], "year": 2024}
        alert = db_helpers.alert(world.project.id, rules[0].id, run.id, key=key)
        await repos.alerts.add(alert)

        # The order of the key's members does not matter; its values and types do.
        assert await repos.alerts.find(rules[0].id, dict(reversed(key.items()))) == alert
        assert await repos.alerts.find(rules[1].id, key) is None
        assert await repos.alerts.find(rules[0].id, {**key, "year": "2024"}) is None
        assert await repos.alerts.find(rules[0].id, {"region": "A"}) is None

        resolved = alert.model_copy(
            update={"state": AlertState.RESOLVED, "resolved_at": factories.NOW}
        )
        await repos.alerts.save(resolved)
        assert await repos.alerts.find(rules[0].id, key) is None


# Operators, snapshots and runs


async def test_an_operator_is_stored_once_with_its_edges_in_order(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        second_source = await repos.operators.add(
            factories.operator(
                world.project.id,
                OperatorKind.SOURCE,
                # An id object instead of its string: the model allows any JSON-like value.
                {"data_source_id": world.source.id, "window": {"start": "2024-01-01"}},
                output=Schema(derived=True),
            )
        )
        joined = factories.operator(
            world.project.id,
            params={"sql": "j"},
            inputs=(second_source.id, world.source_operator.id),
            materializing=True,
        )
        assert await repos.operators.add(joined) == joined
        later = joined.model_copy(update={"created_at": joined.created_at + timedelta(days=1)})
        assert await repos.operators.add(later) == joined

        assert await repos.operators.get(joined.id) == joined
        assert second_source.params["data_source_id"] == str(world.source.id)
        assert {o.id for o in await repos.operators.reading(world.source.id)} == {
            world.source_operator.id,
            second_source.id,
        }
        with pytest.raises(NotFound) as no_source:
            await repos.operators.add(
                factories.operator(
                    world.project.id, OperatorKind.SOURCE, {"data_source_id": str(uuid7())}
                )
            )
        with pytest.raises(NotFound) as no_input:
            await repos.operators.add(
                factories.operator(world.project.id, params={"sql": "x"}, inputs=("op_x",))
            )

    assert (no_source.value.kind, no_input.value.id) == ("data source", "op_x")
    edges = await scalar(
        engine,
        "SELECT json_agg(input_id ORDER BY position) FROM operator_inputs WHERE operator_id = :id",
        id=joined.id,
    )
    assert edges == [second_source.id, world.source_operator.id]
    assert await scalar(engine, "SELECT count(*) FROM operator_inputs") == 3


async def test_the_same_operator_added_by_concurrent_requests_is_stored_once(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
    operator = factories.operator(
        world.project.id, params={"sql": "same"}, inputs=(world.source_operator.id,)
    )

    async def add(delta: int):  # noqa: ANN202
        later = operator.model_copy(
            update={"created_at": operator.created_at + timedelta(days=delta)}
        )
        async with unit_of_work(engine) as repos:
            return await repos.operators.add(later)

    stored = await asyncio.gather(*(add(delta) for delta in range(4)))

    assert len({s.created_at for s in stored}) == 1
    count = "SELECT count(*) FROM operator_inputs WHERE operator_id = :id"
    assert await scalar(engine, count, id=operator.id) == 1


async def test_upstream_lists_a_diamond_once_in_dependency_order(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        project_id = world.project.id
        root = world.source_operator

        async def add(sql: str, *inputs: str) -> Any:
            return await repos.operators.add(
                factories.operator(project_id, params={"sql": sql}, inputs=inputs)
            )

        a = await add("a", root.id)
        b = await add("b", root.id)
        c = await add("c", b.id, a.id)
        d = await add("d", a.id, c.id)

        order = [o.id for o in await repos.operators.upstream(d.id)]
        assert await repos.operators.upstream(root.id) == [root]

    # Depth first in input order: a, then c (which needs b first), then d itself.
    assert order == [root.id, a.id, b.id, c.id, d.id]


async def test_a_chain_longer_than_the_recursion_limit_has_an_upstream(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
    root = world.source_operator.id
    # Written in SQL: a thousand operators through the repository take seconds.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO operators (id, project_id, kind, params, inputs, output,"
                " materializing, created_by, created_at)"
                " SELECT 'op_' || n, project_id, 'transform', jsonb_build_object('sql', n),"
                " jsonb_build_array(CASE WHEN n = 1 THEN id ELSE 'op_' || (n - 1) END),"
                " output, false, created_by, created_at"
                " FROM operators, generate_series(1, 1200) AS n WHERE id = :root"
            ),
            {"root": root},
        )
        await connection.execute(
            text(
                "INSERT INTO operator_inputs (operator_id, position, input_id)"
                " SELECT 'op_' || n, 0, CASE WHEN n = 1 THEN :root ELSE 'op_' || (n - 1) END"
                " FROM generate_series(1, 1200) AS n"
            ),
            {"root": root},
        )

    async with unit_of_work(engine) as repos:
        upstream = await repos.operators.upstream("op_1200")

    assert [o.id for o in upstream] == [root, *(f"op_{n}" for n in range(1, 1201))]


async def test_one_snapshot_per_operator_and_key_is_current(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        operator_id = world.operator.id
        old = factories.snapshot(
            world.project.id,
            operator_id,
            parameters_key="2024",
            period=Interval(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        )
        await repos.snapshots.add(old)
        assert await repos.snapshots.current(operator_id, "2025") is None
        await repos.snapshots.supersede(old.id, factories.NOW)
        new = factories.snapshot(world.project.id, operator_id, parameters_key="2024")
        await repos.snapshots.add(new)

        assert await repos.snapshots.current(operator_id, "2024") == new
        assert await repos.snapshots.get(old.id) == old.model_copy(
            update={"superseded_at": factories.NOW}
        )
        with pytest.raises(IntegrityError):
            await repos.snapshots.add(
                factories.snapshot(world.project.id, operator_id, parameters_key="2024")
            )


async def test_a_run_keeps_the_first_snapshot_it_fixed_even_when_requests_race(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        snapshots = [
            factories.snapshot(world.project.id, world.operator.id, parameters_key=str(n))
            for n in range(4)
        ]
        for snapshot in snapshots:
            await repos.snapshots.add(snapshot)
        run = factories.run(
            world.project.id,
            time_range=TimeRange(start=date(2022, 1, 1), end=date(2024, 12, 31)),
            bindings={"budget": world.operator.id},
        )
        await repos.runs.add(run)
        fixed = await repos.runs.fix_snapshot(run.id, world.operator.id, snapshots[0].id)
        with pytest.raises(NotFound) as no_snapshot:
            await repos.runs.fix_snapshot(run.id, world.source_operator.id, uuid7())

    async def fix(snapshot_id):  # noqa: ANN001, ANN202
        async with unit_of_work(engine) as repos:
            return await repos.runs.fix_snapshot(run.id, world.operator.id, snapshot_id)

    await asyncio.gather(*(fix(s.id) for s in snapshots[1:]))

    async with unit_of_work(engine) as repos:
        [listed] = await repos.runs.list(world.project.id)
    assert no_snapshot.value.kind == "snapshot"
    assert (
        listed
        == fixed
        == run.model_copy(update={"snapshots": {world.operator.id: snapshots[0].id}})
    )
    assert listed.is_scenario
    assert await scalar(engine, "SELECT count(*) FROM run_snapshots") == 1


# Agent turns


async def stored_turn(repos: Repos) -> AgentTurn:
    world = await make_world(repos)
    session = factories.session(world.project.id)
    await repos.sessions.add(session)
    entry = db_helpers.entry(session.id)
    await repos.sessions.add_entry(entry)
    turn = AgentTurn(
        id=uuid7(),
        session_id=session.id,
        prompt_entry_id=entry.id,
        model="gemini/flash",
        created_at=factories.NOW,
    )
    await repos.agent_turns.add(turn)
    return turn


async def test_a_turn_starts_once_stores_its_parts_and_goes_with_its_session(
    engine: AsyncEngine,
) -> None:
    parts = (
        ReasoningPart(text="Looking"),
        ToolPart(
            tool_call_id="c1",
            tool_name="list_pipelines",
            state=ToolState.OUTPUT_AVAILABLE,
            input={"project_id": "p"},
            output=[{"operator_id": "op_1"}],
        ),
        SourcePart(source_id=uuid7(), title="Sotkanet", url="https://example.test"),
        TextPart(text="Done"),
    )
    async with unit_of_work(engine) as repos:
        turn = await stored_turn(repos)
        assert await repos.agent_turns.start(turn.id) is True
        assert await repos.agent_turns.start(turn.id) is False
        await repos.agent_turns.save_parts(turn.id, parts[:2])
        assert (await repos.agent_turns.get(turn.id)).parts == parts[:2]
        finished = await repos.agent_turns.finish(
            turn.id, TurnStatus.FAILED, parts, "boom", factories.NOW
        )
        # Cancelling a finished turn changes nothing.
        assert await repos.agent_turns.request_cancel(turn.id, factories.NOW) == finished

    async with unit_of_work(engine) as repos:
        assert await repos.agent_turns.list(turn.session_id) == [finished]
    assert (finished.status, finished.parts, finished.error) == (TurnStatus.FAILED, parts, "boom")
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM sessions"))
    assert await scalar(engine, "SELECT count(*) FROM agent_turns") == 0


async def test_cancelling_ends_a_queued_turn_and_flags_a_running_one(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        queued = await stored_turn(repos)
        running = await stored_turn(repos)
        await repos.agent_turns.start(running.id)

        cancelled = await repos.agent_turns.request_cancel(queued.id, factories.NOW)
        flagged = await repos.agent_turns.request_cancel(running.id, factories.NOW)

        assert (cancelled.status, cancelled.finished_at) == (TurnStatus.CANCELLED, factories.NOW)
        assert await repos.agent_turns.start(queued.id) is False
        assert flagged.status is TurnStatus.RUNNING
        assert await repos.agent_turns.cancel_requested(running.id) is True


async def test_a_running_turn_commits_its_progress_on_its_own(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        turn = await stored_turn(repos)
    progress = SqlTurnProgress(engine)

    # The worker's own unit of work is open the whole time, as in the run_turn task.
    async with unit_of_work(engine) as worker:
        await worker.agent_turns.get(turn.id)
        assert await progress.start(turn.id) is True
        # Someone presses stop, in a request of their own; it does not wait for the turn.
        async with unit_of_work(engine) as request:
            await asyncio.wait_for(request.agent_turns.request_cancel(turn.id, factories.NOW), 5)
        stop = await progress.checkpoint(turn.id, (TextPart(text="Partly"),))
        async with unit_of_work(engine) as reader:
            seen = await reader.agent_turns.get(turn.id)
        finished = await progress.finish(
            turn.id, TurnStatus.CANCELLED, seen.parts, None, factories.NOW
        )

    assert stop is True
    assert (seen.status, seen.parts) == (TurnStatus.RUNNING, (TextPart(text="Partly"),))
    assert finished.status is TurnStatus.CANCELLED
    assert await scalar(engine, "SELECT status FROM agent_turns") == "cancelled"
