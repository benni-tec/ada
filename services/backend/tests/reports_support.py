"""Shared setup for the report tests; this module holds helpers only.

The dashboard service belongs to another workstream, so it is a small fake here, built on
the dashboard repository. The run service is the fake of api_support with one
addition: executing an operator fixes the current snapshot of every source upstream, as the
real one does, so a report's sources list has something to show.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid7

from dishka import AsyncContainer, Provider, Scope, provide

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.errors import Conflict
from ada.core.models.events import Event
from ada.core.models.operators import Operator, OperatorId, OperatorKind
from ada.core.models.projects import Project
from ada.core.models.runs import Run
from ada.core.models.sessions import Session
from ada.core.models.sources import DataSource
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import (
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    RunRepository,
    SessionRepository,
    SnapshotRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.runs import RunService
from api_support import FakeRuns, Results

YEAR_2024 = TimeRange(start=date(2024, 1, 1), end=date(2024, 12, 31))
FETCHED_A = datetime(2025, 12, 1, 8, 0, tzinfo=UTC)
FETCHED_B = datetime(2025, 11, 1, 8, 0, tzinfo=UTC)


class FakeDashboards(DashboardService):
    """Stands in for workstream G's service: versions numbered from 1, the dashboard
    pointing at the newest."""

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
        dashboard = await self.dashboards.get(id)
        if dashboard.current_version_id is None:
            return None
        return await self.dashboards.get_version(dashboard.current_version_id)

    async def version(self, version_id: Id) -> DashboardVersion:
        return await self.dashboards.get_version(version_id)

    async def versions(self, id: Id) -> Sequence[DashboardVersion]:
        return await self.dashboards.versions(id)

    async def edit(
        self, id: Id, slots: Sequence[Slot], expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        dashboard = await self.dashboards.get(id)
        if dashboard.revision != expected_revision:
            raise Conflict("dashboard", id, expected_revision, dashboard.revision)
        version = DashboardVersion(
            id=uuid7(),
            dashboard_id=id,
            number=len(await self.dashboards.versions(id)) + 1,
            slots=tuple(slots),
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.dashboards.add_version(version)
        await self.dashboards.update(
            dashboard.model_copy(update={"current_version_id": version.id}), expected_revision
        )
        return version

    async def pin_widget(
        self, id: Id, widget_id: Id, slot: str, expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        current = await self.current(id)
        slots = list(current.slots if current else ())
        slots.append(Slot(name=slot, widget_id=widget_id))
        return await self.edit(id, slots, expected_revision, actor)

    async def set_default_time_range(
        self, id: Id, time_range: TimeRange, expected_revision: int
    ) -> Dashboard:
        dashboard = await self.dashboards.get(id)
        return await self.dashboards.update(
            dashboard.model_copy(update={"default_time_range": time_range}), expected_revision
        )


class FixingRuns(FakeRuns):
    """Executing fixes the current snapshot of each source upstream in the run."""

    def __init__(
        self,
        runs: RunRepository,
        results: Results,
        clock: Clock,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        executed: Executed,
    ) -> None:
        super().__init__(runs, snapshots, results, clock)
        self.operators = operators
        self.executed = executed

    async def execute(self, run_id: Id, operator_id: OperatorId) -> Run:
        self.executed.calls.append((run_id, operator_id))
        run = await self.runs.get(run_id)
        for operator in await self.operators.upstream(operator_id):
            if operator.kind is OperatorKind.SOURCE:
                snapshot = await self.snapshots.current(operator.id, "")
                if snapshot is not None:
                    run = await self.runs.fix_snapshot(run_id, operator.id, snapshot.id)
        return run


@dataclass
class Executed:
    calls: list[tuple[Id, OperatorId]] = field(default_factory=list)


class ReportFakes(Provider):
    """Bind after api_support.Overrides, so these replace its run service."""

    scope = Scope.REQUEST

    def __init__(self) -> None:
        super().__init__()
        self.executed = Executed()

    @provide(scope=Scope.APP)
    def executed_(self) -> Executed:
        return self.executed

    dashboards = provide(FakeDashboards, provides=DashboardService)
    runs = provide(FixingRuns, provides=RunService)


@dataclass
class Scene:
    """A project with two sources, three widgets over them, a session and a dashboard.

    - `chart` (line chart) reads `joined`, which joins both sources.
    - `value` and `table` read `cleaned`, which reads source A only.
    - The dashboard shows `value` above `chart`.
    """

    project: Project
    source_a: DataSource
    source_b: DataSource
    operator_a: Operator
    operator_b: Operator
    cleaned: Operator
    joined: Operator
    value: Widget
    table: Widget
    chart: Widget
    session: Session
    dashboard: Dashboard
    dashboard_version: DashboardVersion
    other_project: Project
    stranger: Widget


async def seed(container: AsyncContainer) -> Scene:
    async with container() as request:
        projects = await request.get(ProjectRepository)
        sources = await request.get(DataSourceRepository)
        operators = await request.get(OperatorRepository)
        snapshots = await request.get(SnapshotRepository)
        widgets = await request.get(WidgetRepository)
        sessions = await request.get(SessionRepository)
        dashboards = await request.get(DashboardService)

        project = factories.project(name="Screening")
        other_project = factories.project(name="Other")
        await projects.add(project)
        await projects.add(other_project)
        source_a = factories.data_source(
            project.id, name="Sotkanet", address="https://sotkanet.test/3621.csv"
        )
        source_b = factories.data_source(
            project.id, name="Statistics Finland", address="https://statfin.test/13u5.csv"
        )
        await sources.add(source_a)
        await sources.add(source_b)
        operator_a = await operators.add(_source_operator(project.id, source_a))
        operator_b = await operators.add(_source_operator(project.id, source_b))
        await snapshots.add(
            factories.snapshot(project.id, operator_a.id, content_hash="aaa", fetched_at=FETCHED_A)
        )
        await snapshots.add(
            factories.snapshot(project.id, operator_b.id, content_hash="bbb", fetched_at=FETCHED_B)
        )
        cleaned = await operators.add(
            factories.operator(
                project.id, params={"sql": "SELECT * FROM input_0"}, inputs=(operator_a.id,)
            )
        )
        joined = await operators.add(
            factories.operator(
                project.id,
                params={"sql": "SELECT * FROM input_0 JOIN input_1 USING (region)"},
                inputs=(cleaned.id, operator_b.id),
            )
        )
        value = _widget(project.id, cleaned.id, "value", "Latest coverage")
        table = _widget(project.id, cleaned.id, "table", "Coverage by region")
        chart = _widget(project.id, joined.id, "line-chart", "Coverage and deaths")
        for widget in (value, table, chart):
            await widgets.add(widget)

        stranger_source = factories.data_source(other_project.id)
        await sources.add(stranger_source)
        stranger_operator = await operators.add(_source_operator(other_project.id, stranger_source))
        stranger = _widget(other_project.id, stranger_operator.id, "table", "Elsewhere")
        await widgets.add(stranger)

        session = factories.session(project.id)
        await sessions.add(session)

        dashboard = await dashboards.create(project.id, "Coverage", factories.AGENT)
        dashboard = await dashboards.set_default_time_range(dashboard.id, YEAR_2024, 1)
        dashboard_version = await dashboards.edit(
            dashboard.id,
            [
                Slot(name="trend", widget_id=chart.id, layout={"x": 0, "y": 2, "w": 12, "h": 4}),
                Slot(name="empty", layout={"x": 6, "y": 0, "w": 6, "h": 2}),
                Slot(name="headline", widget_id=value.id, layout={"x": 0, "y": 0, "w": 6, "h": 2}),
            ],
            dashboard.revision,
            factories.AGENT,
        )
        dashboard = await dashboards.get(dashboard.id)
    return Scene(
        project=project,
        source_a=source_a,
        source_b=source_b,
        operator_a=operator_a,
        operator_b=operator_b,
        cleaned=cleaned,
        joined=joined,
        value=value,
        table=table,
        chart=chart,
        session=session,
        dashboard=dashboard,
        dashboard_version=dashboard_version,
        other_project=other_project,
        stranger=stranger,
    )


def _source_operator(project_id: Id, source: DataSource) -> Operator:
    return factories.operator(project_id, OperatorKind.SOURCE, {"data_source_id": str(source.id)})


def _widget(project_id: Id, operator_id: OperatorId, type: str, title: str) -> Widget:
    return Widget(
        id=uuid7(),
        project_id=project_id,
        operator_id=operator_id,
        type=type,
        title=title,
        created_by=factories.AGENT,
        created_at=factories.NOW,
    )


def blocks(*items: dict[str, Any]) -> dict[str, Any]:
    return {"blocks": list(items)}


def heading(text: str, level: int = 2) -> dict[str, Any]:
    return {"type": "heading", "text": text, "level": level}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def shows(widget: Widget | Id, caption: str = "") -> dict[str, Any]:
    widget_id = widget.id if isinstance(widget, Widget) else widget
    block: dict[str, Any] = {"type": "widget", "widget_id": str(widget_id)}
    if caption:
        block["caption"] = caption
    return block


async def published(container: AsyncContainer) -> list[Event]:
    return (await container.get(MemoryEventBus)).published
