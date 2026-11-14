"""Period snapshots in PostgreSQL: one current snapshot per operator and key is a unique
index there, so refetching a period must retire the old snapshot before adding the new
one, and a run fixes the union of the periods like any snapshot."""

from datetime import date
from pathlib import Path

import httpx
import pytest

import factories
from ada.adapters.db.workspace_repositories import SqlSourceCheckLog
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.sources.examples import SOTKANET_BREAST_SCREENING
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.models.sources import FreshnessKind, FreshnessPolicy
from ada.core.models.time import TimeRange
from ada.core.services.pipelines.runs import Runs
from ada.core.services.sources.service import DataSources, source_operator_id
from db_helpers import Repos, engine_for, unit_of_work
from factories import AGENT
from fakes import FixedClock
from test_sources_examples import Replay
from time_world import TODAY

pytestmark = pytest.mark.anyio

DAY = 24 * 60 * 60


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
