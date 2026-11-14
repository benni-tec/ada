"""Period snapshots in PostgreSQL: one current snapshot per operator and key is a unique
index there, so refetching a period must retire the old snapshot before adding the new
one, and a run fixes the union of the periods like any snapshot."""

import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import factories
from ada.adapters.db.workspace_repositories import SqlSourceCheckLog, SqlSourceLocks
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemorySourceLocks
from ada.adapters.sources.examples import SOTKANET_BREAST_SCREENING
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.models.runs import Snapshot
from ada.core.models.sources import FreshnessKind, FreshnessPolicy
from ada.core.models.time import TimeRange
from ada.core.services.pipelines.runs import Runs
from ada.core.services.sources.service import DataSources, source_operator_id
from db_helpers import Repos, engine_for, sql_repos, unit_of_work
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
                MemorySourceLocks(),
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
