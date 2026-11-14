"""Shared setup for the alert tests: the real services of every workstream, the memory
repositories and event bus, DuckDB in tmp_path, and a source reader that returns what the
test tells it. Only the dashboard service, which belongs to another workstream, is a small
stand-in over the dashboard repository. This module holds helpers only."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid7

from dishka import AsyncContainer, Provider, Scope, provide

from ada.adapters.memory.events import MemoryEventBus
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import AlertRule
from ada.core.models.base import Id
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.events import Event
from ada.core.models.operators import Operator
from ada.core.models.schema import Column, ColumnType, MeasureRole, Roles, Schema, TimeRole
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.ports.repositories import DashboardRepository
from ada.core.ports.sources import SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebExplorer
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService
from fakes import FakeExplorer, FakeSourceReader, FakeSourceReaders, FixedClock

TESTER = Actor(kind=ActorKind.USER, name="test")

# Screening coverage per region and year; `hidden` withholds a value.
MEASURE = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="start", type=ColumnType.DATE),
        Column(name="end", type=ColumnType.DATE),
        Column(name="value", type=ColumnType.NUMBER),
        Column(name="hidden", type=ColumnType.BOOLEAN),
    ),
    roles=Roles(
        time=TimeRole(start="start", end="end"),
        measures=(MeasureRole(value="value", suppressed="hidden"),),
    ),
)


def csv(*rows: tuple[str, int, float | None]) -> bytes:
    """region, year, value; a missing value is withheld."""
    lines = ["region,start,end,value,hidden"]
    for region, year, value in rows:
        shown = "" if value is None else f"{value:.1f}"
        lines.append(f"{region},{year}-01-01,{year}-12-31,{shown},{str(value is None).lower()}")
    return ("\n".join(lines) + "\n").encode()


def below(threshold: float) -> dict[str, Any]:
    return {
        "id": "low",
        "kind": "compare",
        "op": "<",
        "args": [
            {"id": "value", "kind": "column", "column": "value"},
            {"id": "limit", "kind": "constant", "value": threshold},
        ],
    }


class StandInDashboards(DashboardService):
    """Enough of the dashboard service for the alert routes: create, read and list."""

    def __init__(self, dashboards: DashboardRepository, clock: Clock) -> None:
        self.dashboards = dashboards
        self.clock = clock

    async def create(self, project_id: Id, name: str, actor: Actor) -> Dashboard:
        dashboard = Dashboard(
            id=uuid7(), project_id=project_id, name=name, created_at=self.clock.now()
        )
        await self.dashboards.add(dashboard)
        return dashboard

    async def get(self, id: Id) -> Dashboard:
        return await self.dashboards.get(id)

    async def list(self, project_id: Id) -> Sequence[Dashboard]:
        return await self.dashboards.list(project_id)

    async def current(self, id: Id) -> DashboardVersion | None:
        raise NotImplementedError

    async def version(self, version_id: Id) -> DashboardVersion:
        raise NotImplementedError

    async def versions(self, id: Id) -> Sequence[DashboardVersion]:
        raise NotImplementedError

    async def edit(
        self, id: Id, slots: Sequence[Slot], expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        raise NotImplementedError

    async def pin_widget(
        self, id: Id, widget_id: Id, slot: str, expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        raise NotImplementedError

    async def set_default_time_range(
        self, id: Id, time_range: TimeRange, expected_revision: int
    ) -> Dashboard:
        raise NotImplementedError


class AlertOverrides(Provider):
    """A clock that stands still, the fake reader for URL sources, and the stand-in
    dashboard service."""

    scope = Scope.REQUEST

    def __init__(self) -> None:
        super().__init__()
        self.clock = FixedClock()
        self.reader = FakeSourceReader()
        self.reader.clock = self.clock

    @provide(scope=Scope.APP)
    def clock_(self) -> Clock:
        return self.clock

    @provide(scope=Scope.APP)
    def explorer(self) -> WebExplorer:
        return FakeExplorer()

    @provide(scope=Scope.APP)
    def readers(self) -> SourceReaders:
        return FakeSourceReaders({AccessKind.URL: self.reader})

    dashboards = provide(StandInDashboards, provides=DashboardService)


@dataclass
class Setup:
    """A project with a source of `MEASURE`, refreshed once, and a dashboard."""

    project_id: Id
    source: DataSource
    measure: Operator
    dashboard: Dashboard


@dataclass
class World:
    container: AsyncContainer
    overrides: AlertOverrides

    @property
    def clock(self) -> FixedClock:
        return self.overrides.clock

    @property
    def reader(self) -> FakeSourceReader:
        return self.overrides.reader

    @asynccontextmanager
    async def alerts(self) -> AsyncIterator[AlertService]:
        """The alert service in one unit of work, which commits when the block ends."""
        async with self.container() as request:
            yield await request.get(AlertService)

    async def events(self) -> list[Event]:
        return (await self.container.get(MemoryEventBus)).published

    async def setup(self, content: bytes) -> Setup:
        self.reader.content = content
        async with self.container() as request:
            project = await (await request.get(ProjectService)).create("Screening")
            sources = await request.get(SourceService)
            source = await sources.register(
                project.id,
                "Coverage",
                AccessKind.URL,
                "https://example.test/coverage.csv",
                DataFormat.CSV,
                declared_schema=MEASURE,
            )
            await sources.refresh(source.id)
            pipelines = await request.get(PipelineService)
            reading = await pipelines.add_source(project.id, source.id, TESTER)
            # A transform, as a measure usually is; its columns are derived.
            measure = await pipelines.add_transform(
                project.id, "SELECT * FROM input_0", [reading.id], TESTER, roles=MEASURE.roles
            )
            dashboards = await request.get(DashboardService)
            dashboard = await dashboards.create(project.id, "Screening", TESTER)
        return Setup(project.id, source, measure, dashboard)

    async def rule(self, setup: Setup, **changes: Any) -> AlertRule:
        arguments: dict[str, Any] = {
            "name": "Coverage below target",
            "operator_id": setup.measure.id,
            "formula": below(80),
            "key_columns": ["region"],
        } | changes
        async with self.alerts() as service:
            return await service.create_rule(setup.dashboard.id, **arguments)

    async def refetch(self, source: DataSource, content: bytes) -> None:
        """New data at the source, fetched by a forced refresh."""
        self.reader.content = content
        async with self.container() as request:
            await (await request.get(SourceService)).refresh(source.id, force=True)
