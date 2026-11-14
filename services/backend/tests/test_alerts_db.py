"""Alert checks on PostgreSQL: the composition root's repositories, with the memory event bus
and DuckDB in tmp_path. Keys go through JSONB and come back to be matched with the next
check's rows; a check's time is written without touching the rule's revision."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from dishka.integrations.fastapi import FastapiProvider

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState
from ada.core.models.events import EventType
from alerts_support import AlertOverrides, World, below, csv
from memory import MemoryBackground

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[World]:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    overrides = AlertOverrides()
    container = create_container(settings, FastapiProvider(), MemoryBackground(), overrides)
    try:
        yield World(container, overrides)
    finally:
        await container.close()


async def test_alerts_fire_stay_and_resolve_on_postgresql(world: World) -> None:
    setup = await world.setup(csv(("north", 2024, 70), ("south", 2024, 90)))
    # A key of two columns, one of them a date, which JSONB stores as text.
    rule = await world.rule(setup, key_columns=["region", "start"])
    checked_at = world.clock.now()
    async with world.alerts() as service:
        (fired,) = await service.check(rule.id)
    assert fired.key == {"region": "north", "start": "2024-01-01"}

    world.clock.advance(hours=1)
    async with world.alerts() as service:
        assert await service.check(rule.id) == []
        (kept,) = await service.alerts(setup.project_id, AlertState.FIRING)
        stored = await service.get_rule(rule.id)
    assert kept.id == fired.id
    assert kept.last_run_id != fired.last_run_id
    assert stored.last_checked_at == checked_at + timedelta(hours=1)
    assert stored.revision == rule.revision

    world.clock.advance(days=1)
    # A stricter formula rather than new data: a refetch with changed content fails on
    # PostgreSQL in wave 1 (the source service adds the new snapshot before superseding the
    # current one, which uq_snapshots_current rejects; reported for integration).
    async with world.alerts() as service:
        await service.update_rule(rule.id, rule.revision, formula=below(60))
        (resolved,) = await service.check(rule.id)
        assert await service.alerts(setup.project_id, AlertState.FIRING) == []
        assert await service.alerts(setup.project_id, AlertState.RESOLVED) == [resolved]
    assert resolved.id == fired.id
    assert resolved.resolved_at == world.clock.now()

    types = [event.type for event in await world.events()]
    assert types.count(EventType.ALERT_FIRING) == 1
    assert types.count(EventType.ALERT_RESOLVED) == 1


async def test_rule_edits_and_due_rules_on_postgresql(world: World) -> None:
    setup = await world.setup(csv(("north", 2024, 70)))
    rule = await world.rule(setup, check_interval_seconds=60)
    async with world.alerts() as service:
        assert [r.id for r in await service.due()] == [rule.id]
        await service.check(rule.id)
        assert await service.due() == []
        edited = await service.update_rule(rule.id, rule.revision, enabled=False)
    assert edited.revision == rule.revision + 1
    assert edited.last_checked_at == world.clock.now()
    world.clock.advance(minutes=5)
    async with world.alerts() as service:
        assert await service.due() == []
        assert await service.list_rules(setup.dashboard.id) == [edited]
