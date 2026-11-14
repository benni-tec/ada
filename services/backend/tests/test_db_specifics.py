"""What only the database repositories have to get right: transactions and concurrent
writers, how rows are laid out, and constraints the memory repositories do not have."""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

import db_helpers
import factories
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import OperatorKind
from ada.core.models.time import Interval
from db_helpers import engine_for, make_world, unit_of_work

pytestmark = pytest.mark.anyio


@pytest.fixture
async def engine(migrated_database_url: str):  # noqa: ANN201
    async with engine_for(migrated_database_url) as engine:
        yield engine


async def scalar(engine: AsyncEngine, statement: str, **parameters: object) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(text(statement), parameters)).scalar_one()


async def test_a_request_that_raises_leaves_nothing_behind(engine: AsyncEngine) -> None:
    project = factories.project()

    with pytest.raises(RuntimeError):
        async with unit_of_work(engine) as repos:
            await repos.projects.add(project)
            raise RuntimeError("boom")

    async with unit_of_work(engine) as repos:
        assert await repos.projects.list() == []


async def test_records_survive_the_request_that_stored_them(engine: AsyncEngine) -> None:
    project = factories.project()
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)

    async with unit_of_work(engine) as repos:
        assert await repos.projects.get(project.id) == project


async def test_a_write_from_a_stale_read_conflicts_across_requests(engine: AsyncEngine) -> None:
    project = factories.project()
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)
    async with unit_of_work(engine) as reader:
        read = await reader.projects.get(project.id)
        async with unit_of_work(engine) as other:
            await other.projects.update(read.model_copy(update={"name": "Theirs"}), 1)

        with pytest.raises(Conflict) as error:
            await reader.projects.update(read.model_copy(update={"name": "Mine"}), 1)

    assert (error.value.kind, error.value.id) == ("project", project.id)
    assert (error.value.expected, error.value.actual) == (1, 2)
    async with unit_of_work(engine) as repos:
        stored = await repos.projects.get(project.id)
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


async def test_updating_an_unknown_record_is_not_found(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        with pytest.raises(NotFound) as error:
            await repos.projects.update(factories.project(), 1)

    assert error.value.kind == "project"


async def test_a_new_record_starts_at_revision_one_whatever_the_model_says(
    engine: AsyncEngine,
) -> None:
    project = factories.project(revision=7)
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)

    async with unit_of_work(engine) as repos:
        assert (await repos.projects.get(project.id)).revision == 1


async def test_record_check_leaves_the_revision_column_alone(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        rule_dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(rule_dashboard)
        rule = db_helpers.alert_rule(world.project.id, rule_dashboard.id, world.operator.id)
        await repos.alert_rules.add(rule)
        await repos.data_sources.record_check(world.source.id, factories.NOW, None, None)
        await repos.alert_rules.record_check(rule.id, factories.NOW)

    assert await scalar(engine, "SELECT revision FROM data_sources") == 1
    assert await scalar(engine, "SELECT revision FROM alert_rules") == 1


async def test_a_refresh_does_not_make_a_concurrent_edit_conflict(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)

    async with unit_of_work(engine) as repos:
        read = await repos.data_sources.get(world.source.id)
    async with unit_of_work(engine) as repos:
        at = factories.NOW + timedelta(hours=1)
        await repos.data_sources.record_check(world.source.id, at, "token", "timed out")
    async with unit_of_work(engine) as repos:
        # The edit read the source before the refresh, and must not undo its outcome.
        updated = await repos.data_sources.update(read.model_copy(update={"name": "Edited"}), 1)

    assert (updated.name, updated.last_checked_at, updated.last_error) == (
        "Edited",
        at,
        "timed out",
    )
    assert updated.revision == 2


async def test_a_rule_edit_does_not_undo_a_check(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        dashboard = db_helpers.dashboard(world.project.id)
        await repos.dashboards.add(dashboard)
        rule = db_helpers.alert_rule(world.project.id, dashboard.id, world.operator.id)
        await repos.alert_rules.add(rule)
        at = factories.NOW + timedelta(hours=1)
        await repos.alert_rules.record_check(rule.id, at)

        updated = await repos.alert_rules.update(rule.model_copy(update={"name": "Edited"}), 1)

    assert (updated.name, updated.last_checked_at, updated.revision) == ("Edited", at, 2)


async def test_record_check_and_supersede_of_unknown_records_are_not_found(
    engine: AsyncEngine,
) -> None:
    unknown = uuid7()
    async with unit_of_work(engine) as repos:
        with pytest.raises(NotFound):
            await repos.data_sources.record_check(unknown, factories.NOW, None, None)
        with pytest.raises(NotFound):
            await repos.alert_rules.record_check(unknown, factories.NOW)
        with pytest.raises(NotFound):
            await repos.snapshots.supersede(unknown, factories.NOW)


async def test_reads_see_changes_made_around_the_orm_in_the_same_request(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        snapshot = factories.snapshot(world.project.id, world.source_operator.id)
        await repos.snapshots.add(snapshot)
        # Both objects are in the session's memory now; the writes below bypass it.
        await repos.data_sources.record_check(world.source.id, factories.NOW, "t", "err")
        await repos.snapshots.supersede(snapshot.id, factories.NOW)

        assert (await repos.data_sources.get(world.source.id)).last_error == "err"
        assert (await repos.snapshots.get(snapshot.id)).superseded_at == factories.NOW


async def test_times_come_back_aware_and_denote_the_same_instant(engine: AsyncEngine) -> None:
    helsinki = timezone(timedelta(hours=2))
    stamp = datetime(2026, 3, 1, 9, 30, tzinfo=helsinki)
    project = factories.project(created_at=stamp)
    async with unit_of_work(engine) as repos:
        await repos.projects.add(project)

    async with unit_of_work(engine) as repos:
        stored = await repos.projects.get(project.id)

    assert stored.created_at.tzinfo is not None
    assert stored.created_at == stamp
    assert stored.created_at.astimezone(UTC) == datetime(2026, 3, 1, 7, 30, tzinfo=UTC)


async def test_lists_follow_creation_time_not_insertion_order(engine: AsyncEngine) -> None:
    older = factories.project(name="Older")
    newer = factories.project(name="Newer", created_at=factories.NOW + timedelta(days=1))
    async with unit_of_work(engine) as repos:
        await repos.projects.add(newer)
        await repos.projects.add(older)
        world = await make_world(repos)
        session = factories.session(world.project.id)
        await repos.sessions.add(session)
        second = db_helpers.entry(session.id, created_at=factories.NOW + timedelta(seconds=1))
        first = db_helpers.entry(session.id)
        await repos.sessions.add_entry(second)
        await repos.sessions.add_entry(first)

        assert [p.id for p in await repos.projects.list() if p.id in (older.id, newer.id)] == [
            older.id,
            newer.id,
        ]
        assert await repos.sessions.entries(session.id) == [first, second]


async def test_an_operator_is_stored_with_its_edges_and_its_data_source(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        left = await repos.operators.add(
            factories.operator(
                world.project.id, params={"sql": "l"}, inputs=(world.source_operator.id,)
            )
        )
        joined = await repos.operators.add(
            factories.operator(
                world.project.id,
                params={"sql": "j"},
                inputs=(left.id, world.source_operator.id),
            )
        )

    edges = await scalar(
        engine,
        "SELECT json_agg(json_build_object('position', position, 'input', input_id)"
        " ORDER BY position) FROM operator_inputs WHERE operator_id = :id",
        id=joined.id,
    )
    assert edges == [
        {"position": 0, "input": left.id},
        {"position": 1, "input": world.source_operator.id},
    ]
    assert await scalar(engine, "SELECT count(*) FROM operator_inputs") == 4
    assert (
        await scalar(
            engine,
            "SELECT data_source_id FROM operators WHERE id = :id",
            id=world.source_operator.id,
        )
        == world.source.id
    )
    assert (
        await scalar(engine, "SELECT count(*) FROM operators WHERE data_source_id IS NOT NULL") == 1
    )


async def test_adding_an_operator_again_adds_no_second_set_of_edges(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        await repos.operators.add(world.operator)
        await repos.operators.add(world.source_operator)

    assert await scalar(engine, "SELECT count(*) FROM operators") == 2
    assert await scalar(engine, "SELECT count(*) FROM operator_inputs") == 1


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
    assert (
        await scalar(
            engine, "SELECT count(*) FROM operator_inputs WHERE operator_id = :id", id=operator.id
        )
        == 1
    )


async def test_params_with_ids_in_them_are_stored_as_json(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        reading = factories.operator(
            world.project.id,
            OperatorKind.SOURCE,
            # An id object instead of its string: the model allows any JSON-like value.
            {"data_source_id": world.source.id, "window": {"start": "2024-01-01"}},
        )
        stored = await repos.operators.add(reading)

        assert stored.params["data_source_id"] == str(world.source.id)
        assert {o.id for o in await repos.operators.reading(world.source.id)} == {
            world.source_operator.id,
            stored.id,
        }


async def test_a_source_operator_needs_a_registered_data_source(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        orphan = factories.operator(
            world.project.id, OperatorKind.SOURCE, {"data_source_id": str(uuid7())}
        )
        with pytest.raises(NotFound) as error:
            await repos.operators.add(orphan)

    assert error.value.kind == "data source"


async def test_an_operator_needs_its_inputs(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        with pytest.raises(NotFound) as error:
            await repos.operators.add(
                factories.operator(world.project.id, params={"sql": "x"}, inputs=("op_missing",))
            )

    assert (error.value.kind, error.value.id) == ("operator", "op_missing")


async def test_a_long_chain_has_an_upstream_in_one_piece(engine: AsyncEngine) -> None:
    length = 1200
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        chain = [world.source_operator]
        for n in range(length):
            chain.append(
                await repos.operators.add(
                    factories.operator(
                        world.project.id, params={"sql": f"step {n}"}, inputs=(chain[-1].id,)
                    )
                )
            )

        upstream = await repos.operators.upstream(chain[-1].id)

    assert [o.id for o in upstream] == [o.id for o in chain]


async def test_a_diamond_lists_each_operator_once_in_dependency_order(
    engine: AsyncEngine,
) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        project_id = world.project.id
        root = world.source_operator
        a = await repos.operators.add(
            factories.operator(project_id, params={"sql": "a"}, inputs=(root.id,))
        )
        b = await repos.operators.add(
            factories.operator(project_id, params={"sql": "b"}, inputs=(root.id,))
        )
        c = await repos.operators.add(
            factories.operator(project_id, params={"sql": "c"}, inputs=(b.id, a.id))
        )
        d = await repos.operators.add(
            factories.operator(project_id, params={"sql": "d"}, inputs=(a.id, c.id))
        )

        order = [o.id for o in await repos.operators.upstream(d.id)]

    # Depth first in input order: a, then c (which needs b first), then d itself.
    assert order == [root.id, a.id, b.id, c.id, d.id]


async def test_only_one_snapshot_per_operator_and_key_is_current(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        await repos.snapshots.add(factories.snapshot(world.project.id, world.operator.id))
        with pytest.raises(IntegrityError):
            await repos.snapshots.add(factories.snapshot(world.project.id, world.operator.id))


async def test_a_snapshot_period_is_stored_as_two_dates(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        snapshot = factories.snapshot(
            world.project.id,
            world.operator.id,
            period=Interval(start=date(2020, 1, 1), end=date(2021, 12, 31)),
        )
        await repos.snapshots.add(snapshot)

    row = await scalar(
        engine,
        "SELECT json_build_array(period_start, period_end) FROM snapshots WHERE id = :id",
        id=snapshot.id,
    )
    assert row == ["2020-01-01", "2021-12-31"]


async def test_fix_snapshot_names_what_is_missing(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        run = factories.run(world.project.id)
        await repos.runs.add(run)
        snapshot = factories.snapshot(world.project.id, world.operator.id)
        await repos.snapshots.add(snapshot)

        with pytest.raises(NotFound) as no_run:
            await repos.runs.fix_snapshot(uuid7(), world.operator.id, snapshot.id)
        with pytest.raises(NotFound) as no_snapshot:
            await repos.runs.fix_snapshot(run.id, world.operator.id, uuid7())

    assert (no_run.value.kind, no_snapshot.value.kind) == ("run", "snapshot")


async def test_fixed_snapshots_are_rows_that_are_only_added(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        first = factories.snapshot(world.project.id, world.operator.id)
        second = factories.snapshot(world.project.id, world.operator.id, parameters_key="b")
        await repos.snapshots.add(first)
        await repos.snapshots.add(second)
        run = factories.run(world.project.id)
        await repos.runs.add(run)
        await repos.runs.fix_snapshot(run.id, world.operator.id, first.id)
        await repos.runs.fix_snapshot(run.id, world.operator.id, second.id)

    assert await scalar(engine, "SELECT count(*) FROM run_snapshots") == 1
    assert await scalar(engine, "SELECT snapshot_id FROM run_snapshots") == first.id


async def test_concurrent_requests_fixing_the_same_operator_agree(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as repos:
        world = await make_world(repos)
        snapshots = [
            factories.snapshot(world.project.id, world.operator.id, parameters_key=str(n))
            for n in range(4)
        ]
        for snapshot in snapshots:
            await repos.snapshots.add(snapshot)
        run = factories.run(world.project.id)
        await repos.runs.add(run)

    async def fix(snapshot_id):  # noqa: ANN001, ANN202
        async with unit_of_work(engine) as repos:
            return await repos.runs.fix_snapshot(run.id, world.operator.id, snapshot_id)

    await asyncio.gather(*(fix(s.id) for s in snapshots))

    async with unit_of_work(engine) as repos:
        stored = await repos.runs.get(run.id)
    assert len(stored.snapshots) == 1
    assert await scalar(engine, "SELECT count(*) FROM run_snapshots") == 1


async def test_an_alert_key_is_matched_exactly_and_only_for_its_rule(engine: AsyncEngine) -> None:
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

        assert await repos.alerts.find(rules[0].id, key) == alert
        assert await repos.alerts.find(rules[1].id, key) is None
        assert await repos.alerts.find(rules[0].id, {**key, "year": "2024"}) is None
