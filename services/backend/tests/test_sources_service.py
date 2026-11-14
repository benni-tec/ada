"""SourceService: registration, revisions, and refreshing by freshness policy."""

from dataclasses import dataclass
from typing import Any

import pytest

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemoryStore,
)
from ada.core.models.actors import ActorKind
from ada.core.models.base import Id
from ada.core.models.errors import Conflict, Invalid, NotFound
from ada.core.models.events import EventType
from ada.core.models.operators import OperatorKind, operator_identity
from ada.core.models.schema import Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
)
from ada.core.services.sources.service import DataSources, source_operator_id
from fakes import FakeAnalysisStore, FakeSourceReader, FakeSourceReaders, FixedClock

pytestmark = pytest.mark.anyio


@dataclass
class World:
    service: DataSources
    memory: MemoryStore
    reader: FakeSourceReader
    store: FakeAnalysisStore
    events: MemoryEventBus
    clock: FixedClock
    project_id: Id

    async def register(self, **changes: Any) -> DataSource:
        arguments: dict[str, Any] = {
            "name": "Screening",
            "access_kind": AccessKind.URL,
            "address": "https://example.test/data.csv",
            "format": DataFormat.CSV,
        }
        return await self.service.register(self.project_id, **(arguments | changes))

    def snapshots(self, source: DataSource) -> list[Any]:
        operator_id = source_operator_id(source)
        return [s for s in self.memory.snapshots.values() if s.operator_id == operator_id]

    def current(self, source: DataSource) -> list[Any]:
        return [s for s in self.snapshots(source) if s.superseded_at is None]


@pytest.fixture
async def world() -> World:
    memory = MemoryStore()
    clock = FixedClock()
    reader = FakeSourceReader(b"region,value\nHelsinki,74.3\n")
    reader.clock = clock
    store = FakeAnalysisStore()
    events = MemoryEventBus()
    project = factories.project()
    await MemoryProjectRepository(memory).add(project)
    service = DataSources(
        projects=MemoryProjectRepository(memory),
        sources=MemoryDataSourceRepository(memory),
        operators=MemoryOperatorRepository(memory),
        snapshots=MemorySnapshotRepository(memory),
        readers=FakeSourceReaders({AccessKind.URL: reader, AccessKind.REQUEST: reader}),
        checks=MemorySourceCheckLog(memory),
        store=store,
        events=events,
        clock=clock,
    )
    return World(service, memory, reader, store, events, clock, project.id)


# Registration


async def test_register_stores_the_source_and_its_source_operator(world: World) -> None:
    declared = factories.SCHEMA
    source = await world.register(declared_schema=declared, options={"rows": "data"})

    assert await world.service.get(source.id) == source
    assert (source.revision, source.created_at, source.options) == (
        1,
        world.clock.at,
        {"rows": "data"},
    )
    operator = world.memory.operators[source_operator_id(source)]
    assert operator.id == operator_identity(
        world.project_id, OperatorKind.SOURCE, {"data_source_id": str(source.id)}, ()
    )
    assert operator.params == {"data_source_id": str(source.id)}
    assert (operator.inputs, operator.output, operator.materializing) == ((), declared, True)
    assert (operator.created_by.kind, operator.created_by.name) == (ActorKind.SYSTEM, "ada")


async def test_a_source_without_a_declared_schema_has_an_empty_output(world: World) -> None:
    source = await world.register()

    assert world.memory.operators[source_operator_id(source)].output == Schema()


async def test_register_needs_an_existing_project(world: World) -> None:
    with pytest.raises(NotFound):
        await world.service.register(
            factories.project().id, "x", AccessKind.URL, "https://x.test", DataFormat.CSV
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "  "},
        {"address": ""},
        {"access_kind": AccessKind.BROWSER},
        {"freshness": FreshnessPolicy(kind=FreshnessKind.TTL)},
        {"freshness": FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=0)},
        {"options": {"rows": 3}},
        {"options": {"csv": {"delimiter": ";;"}}},
    ],
)
async def test_register_refuses_what_cannot_work(world: World, changes: dict[str, Any]) -> None:
    with pytest.raises(Invalid):
        await world.register(**changes)

    assert world.memory.data_sources == {}
    assert world.memory.operators == {}


async def test_list_returns_the_projects_sources(world: World) -> None:
    first = await world.register(name="First")
    second = await world.register(name="Second")

    assert await world.service.list(world.project_id) == [first, second]
    with pytest.raises(NotFound):
        await world.service.list(factories.project().id)


# Updates


async def test_update_changes_only_the_given_fields(world: World) -> None:
    source = await world.register()
    policy = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=60)

    updated = await world.service.update(source.id, 1, name="Renamed", freshness=policy)

    assert (updated.name, updated.freshness, updated.revision) == ("Renamed", policy, 2)
    assert (updated.address, updated.options) == (source.address, source.options)
    assert await world.service.get(source.id) == updated


async def test_update_with_a_stale_revision_conflicts(world: World) -> None:
    source = await world.register()
    await world.service.update(source.id, 1, name="First")

    with pytest.raises(Conflict):
        await world.service.update(source.id, 1, name="Second")

    assert (await world.service.get(source.id)).name == "First"


async def test_update_refuses_a_policy_that_cannot_work(world: World) -> None:
    source = await world.register()

    with pytest.raises(Invalid):
        await world.service.update(source.id, 1, freshness=FreshnessPolicy(kind=FreshnessKind.TTL))


# Refreshing


async def test_the_first_refresh_writes_a_snapshot(world: World) -> None:
    source = await world.register(declared_schema=factories.SCHEMA)

    result = await world.service.refresh(source.id)

    assert result.changed
    [snapshot] = world.snapshots(source)
    assert result.snapshot_ids == (snapshot.id,)
    [written] = world.store.written
    assert written.content == b"region,value\nHelsinki,74.3\n"
    assert snapshot.operator_id == source_operator_id(source)
    assert (snapshot.parameters_key, snapshot.period) == ("", None)
    assert snapshot.location == f"memory://{world.project_id}/{snapshot.content_hash}"
    assert (snapshot.fetched_at, snapshot.superseded_at) == (world.clock.at, None)
    stored = await world.service.get(source.id)
    assert (stored.last_checked_at, stored.last_error) == (world.clock.at, None)
    [event] = world.events.published
    assert event.type is EventType.SOURCE_REFRESHED
    assert event.payload == {"data_source_id": str(source.id), "changed": True}


async def test_the_reader_gets_an_open_time_range(world: World) -> None:
    source = await world.register()

    await world.service.refresh(source.id)

    [(_, time_range)] = world.reader.fetches
    assert (time_range.start, time_range.end) == (None, None)


async def test_the_options_shape_the_data_before_it_is_stored(world: World) -> None:
    world.reader.content = b'{"data": [{"region": "Helsinki", "survival": {"value": 7}}]}'
    world.reader.format = DataFormat.JSON
    source = await world.register(format=DataFormat.JSON, options={"rows": "data"})

    await world.service.refresh(source.id)

    [written] = world.store.written
    assert written.content == b'[{"region":"Helsinki","survival_value":7}]'


async def test_a_manual_source_refreshes_only_when_asked(world: World) -> None:
    source = await world.register()
    await world.service.refresh(source.id)
    world.clock.advance(days=365)

    result = await world.service.refresh(source.id)

    assert not result.changed
    assert len(world.reader.fetches) == 1
    # A check that did not happen is not reported.
    assert len(world.events.published) == 1

    world.reader.content = b"region,value\nHelsinki,80.1\n"
    forced = await world.service.refresh(source.id, force=True)

    assert forced.changed
    assert len(world.reader.fetches) == 2


async def test_a_push_source_waits_like_a_manual_one(world: World) -> None:
    source = await world.register(freshness=FreshnessPolicy(kind=FreshnessKind.PUSH))
    await world.service.refresh(source.id)
    world.clock.advance(days=30)

    assert not (await world.service.refresh(source.id)).changed
    assert len(world.reader.fetches) == 1


async def test_a_new_content_supersedes_the_old_snapshot(world: World) -> None:
    source = await world.register()
    await world.service.refresh(source.id)
    [old] = world.snapshots(source)
    world.reader.content = b"region,value\nHelsinki,80.1\n"
    world.clock.advance(hours=1)

    result = await world.service.refresh(source.id, force=True)

    assert result.changed
    [current] = world.current(source)
    assert result.snapshot_ids == (current.id,)
    assert current.id != old.id
    assert world.memory.snapshots[old.id].superseded_at == world.clock.at


async def test_identical_content_adds_no_snapshot(world: World) -> None:
    source = await world.register()
    await world.service.refresh(source.id)
    world.clock.advance(hours=1)

    result = await world.service.refresh(source.id, force=True)

    assert (result.changed, result.snapshot_ids) == (False, ())
    assert len(world.snapshots(source)) == 1
    assert (await world.service.get(source.id)).last_checked_at == world.clock.at
    assert world.events.published[-1].payload == {
        "data_source_id": str(source.id),
        "changed": False,
    }


async def test_a_ttl_source_refetches_after_its_lifetime(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    )
    await world.service.refresh(source.id)

    world.clock.advance(minutes=59)
    await world.service.refresh(source.id)
    assert len(world.reader.fetches) == 1

    world.clock.advance(minutes=1)
    await world.service.refresh(source.id)
    assert len(world.reader.fetches) == 2


async def test_the_lifetime_counts_from_the_last_check(world: World) -> None:
    # An identical refetch writes no snapshot, but the source was still checked.
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    )
    await world.service.refresh(source.id)
    world.clock.advance(hours=1)
    await world.service.refresh(source.id)
    world.clock.advance(minutes=30)

    await world.service.refresh(source.id)

    assert len(world.reader.fetches) == 2


async def test_a_probe_with_the_same_token_skips_the_fetch(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = "2026-06-12"
    await world.service.refresh(source.id)
    assert (await world.service.get(source.id)).last_probe_token == "2026-06-12"
    world.clock.advance(minutes=5)

    result = await world.service.refresh(source.id)

    assert not result.changed
    assert len(world.reader.probes) == 2
    assert len(world.reader.fetches) == 1
    assert (await world.service.get(source.id)).last_checked_at == world.clock.at
    assert world.events.published[-1].type is EventType.SOURCE_REFRESHED


async def test_a_probe_with_a_new_token_fetches(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = "2026-06-12"
    await world.service.refresh(source.id)
    world.clock.advance(minutes=5)
    world.reader.token = "2026-11-01"
    world.reader.content = b"region,value\nHelsinki,80.1\n"

    result = await world.service.refresh(source.id)

    assert result.changed
    assert len(world.reader.fetches) == 2
    assert (await world.service.get(source.id)).last_probe_token == "2026-11-01"


async def test_a_probe_runs_at_most_once_per_lifetime(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = "a"
    await world.service.refresh(source.id)
    world.clock.advance(seconds=30)

    await world.service.refresh(source.id)

    assert len(world.reader.probes) == 1


async def test_a_source_without_a_token_is_fetched(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    await world.service.refresh(source.id)
    world.clock.advance(minutes=5)

    await world.service.refresh(source.id)

    assert len(world.reader.fetches) == 2


async def test_a_forced_refresh_does_not_probe(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = "a"
    await world.service.refresh(source.id)

    await world.service.refresh(source.id, force=True)

    assert (len(world.reader.probes), len(world.reader.fetches)) == (1, 2)


async def test_a_failed_fetch_keeps_the_old_snapshot_and_records_the_error(world: World) -> None:
    source = await world.register()
    await world.service.refresh(source.id)
    [old] = world.snapshots(source)
    world.reader.content = RuntimeError("GET https://example.test/data.csv answered 503")
    world.clock.advance(hours=1)

    with pytest.raises(RuntimeError):
        await world.service.refresh(source.id, force=True)

    assert world.current(source) == [old]
    stored = await world.service.get(source.id)
    assert stored.last_error == "GET https://example.test/data.csv answered 503"
    assert stored.last_checked_at == world.clock.at
    event = world.events.published[-1]
    assert event.type is EventType.SOURCE_REFRESH_FAILED
    assert event.payload == {
        "data_source_id": str(source.id),
        "changed": False,
        "error": "GET https://example.test/data.csv answered 503",
    }

    world.reader.content = b"region,value\nHelsinki,80.1\n"
    await world.service.refresh(source.id, force=True)
    assert (await world.service.get(source.id)).last_error is None


async def test_a_failed_fetch_after_a_new_token_keeps_the_old_token(world: World) -> None:
    # Otherwise the next probe would match and the new data would never be fetched.
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = "old"
    await world.service.refresh(source.id)
    world.clock.advance(minutes=5)
    world.reader.token = "new"
    world.reader.content = RuntimeError("timeout")

    with pytest.raises(RuntimeError):
        await world.service.refresh(source.id)

    assert (await world.service.get(source.id)).last_probe_token == "old"


async def test_a_failed_probe_fails_the_refresh(world: World) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=60)
    )
    world.reader.token = Invalid("The probe has no field 'data-updated'")

    with pytest.raises(Invalid):
        await world.service.refresh(source.id)

    assert world.reader.fetches == []
    assert (await world.service.get(source.id)).last_error == (
        "The probe has no field 'data-updated'"
    )


async def test_content_that_does_not_fit_the_options_fails_the_refresh(world: World) -> None:
    world.reader.content = b'{"other": []}'
    world.reader.format = DataFormat.JSON
    source = await world.register(format=DataFormat.JSON, options={"rows": "data"})

    with pytest.raises(Invalid):
        await world.service.refresh(source.id)

    assert world.store.written == []
    assert world.snapshots(source) == []
    assert (await world.service.get(source.id)).last_error is not None


async def test_refreshing_an_unknown_source_is_not_found(world: World) -> None:
    with pytest.raises(NotFound):
        await world.service.refresh(factories.project().id)


# Due


async def test_due_lists_the_sources_whose_policy_says_now(world: World) -> None:
    hourly = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    manual = await world.register(name="Manual")
    ttl = await world.register(name="TTL", freshness=hourly)
    probe = await world.register(
        name="Probe", freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=86400)
    )
    push = await world.register(name="Push", freshness=FreshnessPolicy(kind=FreshnessKind.PUSH))

    # Never refreshed: the scheduled policies are due, the others wait to be asked.
    assert [s.id for s in await world.service.due()] == [ttl.id, probe.id]

    for source in (manual, ttl, probe, push):
        await world.service.refresh(source.id)
    assert await world.service.due() == []

    world.clock.advance(hours=1)
    assert [s.id for s in await world.service.due()] == [ttl.id]

    world.clock.advance(days=1)
    assert [s.id for s in await world.service.due()] == [ttl.id, probe.id]


async def test_a_failed_source_is_due_again_after_its_lifetime(world: World) -> None:
    source = await world.register(freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=60))
    await world.service.refresh(source.id)
    world.clock.advance(minutes=1)
    world.reader.content = RuntimeError("down")
    with pytest.raises(RuntimeError):
        await world.service.refresh(source.id)

    assert await world.service.due() == []
    world.clock.advance(minutes=1)
    assert [s.id for s in await world.service.due()] == [source.id]
