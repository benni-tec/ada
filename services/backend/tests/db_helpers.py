"""Shared by the tests of the database repositories: one set of repositories per backend,
so the same expectations run against the memory repositories (the reference) and the
SQLAlchemy ones, and builders for the records the shared factories do not cover."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid7

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import factories
from ada.adapters.db.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from ada.adapters.db.pipeline_repositories import (
    SqlOperatorRepository,
    SqlRunRepository,
    SqlSnapshotRepository,
)
from ada.adapters.db.reporting_repositories import (
    SqlDashboardRepository,
    SqlReportRepository,
    SqlTemplateRepository,
)
from ada.adapters.db.workspace_repositories import (
    SqlDataSourceRepository,
    SqlProjectRepository,
    SqlSessionRepository,
    SqlWidgetRepository,
)
from ada.adapters.memory.repositories import (
    MemoryAlertRepository,
    MemoryAlertRuleRepository,
    MemoryDashboardRepository,
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemoryReportRepository,
    MemoryRunRepository,
    MemorySessionRepository,
    MemorySnapshotRepository,
    MemoryStore,
    MemoryTemplateRepository,
    MemoryWidgetRepository,
)
from ada.core.models.alerts import Alert, AlertRule, AlertState
from ada.core.models.base import Id
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.operators import OperatorId, OperatorKind
from ada.core.models.reports import Report, ReportVersion, Template, TemplateKind
from ada.core.models.sessions import EntryKind, SessionEntry
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import (
    AlertRepository,
    AlertRuleRepository,
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    ReportRepository,
    RunRepository,
    SessionRepository,
    SnapshotRepository,
    TemplateRepository,
    WidgetRepository,
)


@dataclass
class Repos:
    projects: ProjectRepository
    data_sources: DataSourceRepository
    sessions: SessionRepository
    operators: OperatorRepository
    snapshots: SnapshotRepository
    runs: RunRepository
    widgets: WidgetRepository
    dashboards: DashboardRepository
    templates: TemplateRepository
    reports: ReportRepository
    alert_rules: AlertRuleRepository
    alerts: AlertRepository


def memory_repos() -> Repos:
    store = MemoryStore()
    return Repos(
        MemoryProjectRepository(store),
        MemoryDataSourceRepository(store),
        MemorySessionRepository(store),
        MemoryOperatorRepository(store),
        MemorySnapshotRepository(store),
        MemoryRunRepository(store),
        MemoryWidgetRepository(store),
        MemoryDashboardRepository(store),
        MemoryTemplateRepository(store),
        MemoryReportRepository(store),
        MemoryAlertRuleRepository(store),
        MemoryAlertRepository(store),
    )


def sql_repos(session: AsyncSession) -> Repos:
    return Repos(
        SqlProjectRepository(session),
        SqlDataSourceRepository(session),
        SqlSessionRepository(session),
        SqlOperatorRepository(session),
        SqlSnapshotRepository(session),
        SqlRunRepository(session),
        SqlWidgetRepository(session),
        SqlDashboardRepository(session),
        SqlTemplateRepository(session),
        SqlReportRepository(session),
        SqlAlertRuleRepository(session),
        SqlAlertRepository(session),
    )


@asynccontextmanager
async def engine_for(url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url)
    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def unit_of_work(engine: AsyncEngine) -> AsyncIterator[Repos]:
    """What the container gives one request: repositories on one session that commits when
    the block ends and rolls back when it raises (providers/infrastructure.py)."""
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        yield sql_repos(session)


@dataclass
class World:
    """The records most others hang on, already stored."""

    project: Any
    source: Any
    source_operator: Any
    operator: Any


async def make_world(repos: Repos) -> World:
    project = factories.project()
    await repos.projects.add(project)
    source = factories.data_source(project.id)
    await repos.data_sources.add(source)
    source_operator = await repos.operators.add(
        factories.operator(project.id, OperatorKind.SOURCE, {"data_source_id": str(source.id)})
    )
    operator = await repos.operators.add(
        factories.operator(project.id, inputs=(source_operator.id,))
    )
    return World(project, source, source_operator, operator)


def entry(session_id: Id, **changes: Any) -> SessionEntry:
    return SessionEntry(
        **{
            "id": uuid7(),
            "session_id": session_id,
            "kind": EntryKind.MESSAGE,
            "text": "hello",
            "actor": factories.AGENT,
            "created_at": factories.NOW,
        }
        | changes
    )


def widget(project_id: Id, operator_id: OperatorId, **changes: Any) -> Widget:
    return Widget(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "operator_id": operator_id,
            "type": "table",
            "title": "Widget",
            "spec": {"x": "region", "limit": 10},
            "note": "to see the values",
            "created_by": factories.AGENT,
            "created_at": factories.NOW,
        }
        | changes
    )


def dashboard(project_id: Id, **changes: Any) -> Dashboard:
    return Dashboard(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "name": "Dashboard",
            "default_time_range": TimeRange(start=date(2024, 1, 1), end=date(2024, 12, 31)),
            "created_at": factories.NOW,
        }
        | changes
    )


def dashboard_version(dashboard_id: Id, number: int, **changes: Any) -> DashboardVersion:
    return DashboardVersion(
        **{
            "id": uuid7(),
            "dashboard_id": dashboard_id,
            "number": number,
            "slots": (Slot(name="top", description="headline", layout={"w": 6, "h": 2}),),
            "created_by": factories.AGENT,
            "created_at": factories.NOW,
        }
        | changes
    )


def template(project_id: Id, **changes: Any) -> Template:
    return Template(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "name": "Template",
            "kind": TemplateKind.REPORT,
            "slots": (Slot(name="chart"),),
            "content": {"type": "page", "children": [{"type": "text", "text": "Hi"}]},
            "created_at": factories.NOW,
        }
        | changes
    )


def report(project_id: Id, **changes: Any) -> Report:
    return Report(
        **{"id": uuid7(), "project_id": project_id, "name": "Report", "created_at": factories.NOW}
        | changes
    )


def report_version(
    report_id: Id, run_id: Id, version: str = "1.0.0", **changes: Any
) -> ReportVersion:
    return ReportVersion(
        **{
            "id": uuid7(),
            "report_id": report_id,
            "version": version,
            "run_id": run_id,
            "time_range": TimeRange(start=date(2023, 1, 1)),
            "content": {"type": "widget", "widget_id": str(uuid7())},
            "created_by": factories.AGENT,
            "created_at": factories.NOW,
        }
        | changes
    )


def alert_rule(
    project_id: Id, dashboard_id: Id, operator_id: OperatorId, **changes: Any
) -> AlertRule:
    return AlertRule(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "dashboard_id": dashboard_id,
            "name": "Rule",
            "operator_id": operator_id,
            "formula": {"op": "<", "args": [{"col": "value"}, 10]},
            "key_columns": ("region",),
            "check_interval_seconds": 3600,
            "created_at": factories.NOW,
        }
        | changes
    )


def alert(project_id: Id, rule_id: Id, run_id: Id, **changes: Any) -> Alert:
    return Alert(
        **{
            "id": uuid7(),
            "project_id": project_id,
            "rule_id": rule_id,
            "key": {"region": "Uusimaa"},
            "state": AlertState.FIRING,
            "since_run_id": run_id,
            "last_run_id": run_id,
            "started_at": factories.NOW,
        }
        | changes
    )
