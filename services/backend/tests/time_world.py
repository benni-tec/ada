"""The services of the roles and time tests, wired as the composition root wires them, over
the memory repositories, the real DuckDB store in a temporary directory and the HTTP
readers answering from the recorded responses (tests/recordings). Nothing reaches the
network."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

import factories
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDashboardRepository,
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemoryRunRepository,
    MemorySessionRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemorySourceLocks,
    MemoryStore,
    MemoryWidgetRepository,
)
from ada.adapters.sources.examples import ExampleSource
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.models.base import Id
from ada.core.models.operators import Operator
from ada.core.models.runs import Run, Snapshot
from ada.core.models.sources import DataSource
from ada.core.models.time import TimeRange
from ada.core.services.pipelines.runs import Runs
from ada.core.services.pipelines.service import Pipelines
from ada.core.services.sessions.service import Sessions
from ada.core.services.sources.service import DataSources, source_operator_id
from ada.core.services.widgets.service import Widgets
from factories import AGENT
from fakes import FixedClock
from test_sources_examples import Replay

# The day the recordings were made.
TODAY = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


class Transport(httpx.AsyncBaseTransport):
    """Replays the recordings, or fails every request while `down` is set, as an
    unreachable source does."""

    def __init__(self, replay: Replay) -> None:
        self.replay = replay
        self.mock = httpx.MockTransport(replay)
        self.down = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("the source is down", request=request)
        return await self.mock.handle_async_request(request)


class World:
    def __init__(self, tmp_path: Path, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.memory = memory = MemoryStore()
        self.clock = FixedClock(TODAY)
        self.replay = Replay()
        self.transport = Transport(self.replay)
        self.store = DuckDbAnalysisStore(tmp_path / "data")
        self.events = MemoryEventBus()
        self.project = factories.project()
        projects = MemoryProjectRepository(memory)
        self.data_sources = MemoryDataSourceRepository(memory)
        self.operators = MemoryOperatorRepository(memory)
        self.snapshots = MemorySnapshotRepository(memory)
        self.widget_repository = MemoryWidgetRepository(memory)
        readers = HttpSourceReaders(create_client(transport or self.transport), self.clock)
        self.sources = DataSources(
            projects=projects,
            sources=self.data_sources,
            operators=self.operators,
            snapshots=self.snapshots,
            readers=readers,
            checks=MemorySourceCheckLog(memory),
            store=self.store,
            events=self.events,
            clock=self.clock,
            locks=MemorySourceLocks(),
        )
        self.pipelines = Pipelines(
            self.operators, self.data_sources, self.snapshots, self.sources, self.store, self.clock
        )
        self.runs = Runs(
            MemoryRunRepository(memory),
            self.operators,
            self.snapshots,
            self.sources,
            self.store,
            self.events,
            self.clock,
        )
        sessions = MemorySessionRepository(memory)
        self.widgets = Widgets(
            self.widget_repository,
            self.operators,
            sessions,
            self.data_sources,
            Sessions(
                sessions,
                projects,
                MemoryDashboardRepository(memory),
                self.operators,
                self.widget_repository,
                self.events,
                self.clock,
            ),
            self.runs,
            self.events,
            self.clock,
        )
        memory.projects[self.project.id] = self.project

    @property
    def project_id(self) -> Id:
        return self.project.id

    async def register(self, example: ExampleSource, **changes: Any) -> DataSource:
        arguments = example.registration() | changes
        return await self.sources.register(self.project_id, **arguments)

    async def operator(self, source: DataSource) -> Operator:
        return await self.operators.get(source_operator_id(source))

    async def run(self, start: int | None = None, end: int | None = None) -> Run:
        """A run for whole years, e.g. run(2022, 2024)."""
        time_range = TimeRange(
            start=date(start, 1, 1) if start else None, end=date(end, 12, 31) if end else None
        )
        return await self.runs.start(self.project_id, AGENT, time_range)

    async def rows(
        self, operator: Operator, run: Run, limit: int = 5000
    ) -> list[dict[str, object]]:
        result = await self.runs.read(run.id, operator.id, limit)
        names = [column.name for column in result.columns]
        return [dict(zip(names, row, strict=True)) for row in result.rows]

    async def transform(self, sql: str, *inputs: Operator, **options: Any) -> Operator:
        return await self.pipelines.add_transform(
            self.project_id, sql, [i.id for i in inputs], AGENT, **options
        )

    def requests(self) -> list[str]:
        """The requests so far, as path and sorted query, and forgets them."""
        seen = [
            f"{r.url.path}?{'&'.join(sorted(f'{k}={v}' for k, v in r.url.params.multi_items()))}"
            for r in self.replay.requests
        ]
        self.replay.requests.clear()
        return seen

    def period_snapshots(self, source: DataSource, current: bool = True) -> list[Snapshot]:
        operator_id = source_operator_id(source)
        return sorted(
            (
                s
                for s in self.memory.snapshots.values()
                if s.operator_id == operator_id
                and s.parameters_key.startswith("period:")
                and (s.superseded_at is None or not current)
            ),
            key=lambda s: (s.parameters_key, s.fetched_at),
        )
