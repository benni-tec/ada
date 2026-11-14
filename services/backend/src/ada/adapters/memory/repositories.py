"""Repositories that keep everything in process memory.

They implement the repository ports exactly, including NotFound and the revision check,
so services can be built and tested before the database repositories exist, and tests of
anything above the ports need no database. Nothing here survives a restart.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ada.core.models.alerts import Alert, AlertRule, AlertState
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.dashboards import Dashboard, DashboardVersion
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import Operator, OperatorId, OperatorKind
from ada.core.models.projects import Project
from ada.core.models.reports import Report, ReportVersion, Template
from ada.core.models.runs import Run, Snapshot
from ada.core.models.sessions import Session, SessionEntry
from ada.core.models.sources import DataSource
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
from ada.core.ports.sources import SourceCheckLog, SourceLocks


class MemoryStore:
    """The shared state behind all memory repositories: one dict per kind of record, in
    insertion order. One instance per process (or per test)."""

    def __init__(self) -> None:
        self.projects: dict[Id, Project] = {}
        self.data_sources: dict[Id, DataSource] = {}
        self.sessions: dict[Id, Session] = {}
        self.session_entries: list[SessionEntry] = []
        self.operators: dict[OperatorId, Operator] = {}
        self.snapshots: dict[Id, Snapshot] = {}
        self.runs: dict[Id, Run] = {}
        self.widgets: dict[Id, Widget] = {}
        self.dashboards: dict[Id, Dashboard] = {}
        self.dashboard_versions: dict[Id, DashboardVersion] = {}
        self.templates: dict[Id, Template] = {}
        self.reports: dict[Id, Report] = {}
        self.report_versions: dict[Id, ReportVersion] = {}
        self.alert_rules: dict[Id, AlertRule] = {}
        self.alerts: dict[Id, Alert] = {}


def _get[K, M](records: dict[K, M], kind: str, id: K) -> M:
    try:
        return records[id]
    except KeyError:
        raise NotFound(kind, id) from None


def _update[M: DomainModel](records: dict[Any, M], kind: str, model: M, expected: int) -> M:
    """The revision check every mutable record shares. Models carry `id` and `revision`."""
    id = model.id  # type: ignore[attr-defined]
    stored = _get(records, kind, id)
    actual = stored.revision  # type: ignore[attr-defined]
    if actual != expected:
        raise Conflict(kind, id, expected, actual)
    updated = model.model_copy(update={"revision": expected + 1})
    records[id] = updated
    return updated


def _in_project[M](records: dict[Any, M], project_id: Id) -> list[M]:
    return [r for r in records.values() if r.project_id == project_id]  # type: ignore[attr-defined]


class MemoryProjectRepository(ProjectRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Project:
        return _get(self.store.projects, "project", id)

    async def list(self) -> Sequence[Project]:
        return list(self.store.projects.values())

    async def add(self, project: Project) -> None:
        self.store.projects[project.id] = project

    async def update(self, project: Project, expected_revision: int) -> Project:
        return _update(self.store.projects, "project", project, expected_revision)


class MemoryDataSourceRepository(DataSourceRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> DataSource:
        return _get(self.store.data_sources, "data source", id)

    async def list(self, project_id: Id) -> Sequence[DataSource]:
        return _in_project(self.store.data_sources, project_id)

    async def list_all(self) -> Sequence[DataSource]:
        return list(self.store.data_sources.values())

    async def add(self, source: DataSource) -> None:
        self.store.data_sources[source.id] = source

    async def update(self, source: DataSource, expected_revision: int) -> DataSource:
        return _update(self.store.data_sources, "data source", source, expected_revision)

    async def record_check(
        self, id: Id, at: datetime, probe_token: str | None, error: str | None
    ) -> None:
        source = await self.get(id)
        self.store.data_sources[id] = source.model_copy(
            update={"last_checked_at": at, "last_probe_token": probe_token, "last_error": error}
        )


class MemorySessionRepository(SessionRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Session:
        return _get(self.store.sessions, "session", id)

    async def list(self, project_id: Id) -> Sequence[Session]:
        return _in_project(self.store.sessions, project_id)

    async def add(self, session: Session) -> None:
        self.store.sessions[session.id] = session

    async def update(self, session: Session, expected_revision: int) -> Session:
        return _update(self.store.sessions, "session", session, expected_revision)

    async def add_entry(self, entry: SessionEntry) -> None:
        await self.get(entry.session_id)
        self.store.session_entries.append(entry)

    async def entries(self, session_id: Id) -> Sequence[SessionEntry]:
        return [e for e in self.store.session_entries if e.session_id == session_id]


class MemoryOperatorRepository(OperatorRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: OperatorId) -> Operator:
        return _get(self.store.operators, "operator", id)

    async def add(self, operator: Operator) -> Operator:
        return self.store.operators.setdefault(operator.id, operator)

    async def list(self, project_id: Id) -> Sequence[Operator]:
        return _in_project(self.store.operators, project_id)

    async def upstream(self, id: OperatorId) -> Sequence[Operator]:
        ordered: dict[OperatorId, Operator] = {}

        async def visit(operator_id: OperatorId) -> None:
            if operator_id in ordered:
                return
            operator = await self.get(operator_id)
            for input_id in operator.inputs:
                await visit(input_id)
            ordered[operator_id] = operator

        await visit(id)
        return list(ordered.values())

    async def reading(self, data_source_id: Id) -> Sequence[Operator]:
        return [
            operator
            for operator in self.store.operators.values()
            if operator.kind is OperatorKind.SOURCE
            and operator.params.get("data_source_id") == str(data_source_id)
        ]


class MemorySnapshotRepository(SnapshotRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Snapshot:
        return _get(self.store.snapshots, "snapshot", id)

    async def add(self, snapshot: Snapshot) -> None:
        self.store.snapshots[snapshot.id] = snapshot

    async def current(self, operator_id: OperatorId, parameters_key: str) -> Snapshot | None:
        for snapshot in self.store.snapshots.values():
            if (
                snapshot.operator_id == operator_id
                and snapshot.parameters_key == parameters_key
                and snapshot.superseded_at is None
            ):
                return snapshot
        return None

    async def supersede(self, id: Id, at: datetime) -> None:
        snapshot = await self.get(id)
        self.store.snapshots[id] = snapshot.model_copy(update={"superseded_at": at})

    async def list(self, operator_id: OperatorId) -> Sequence[Snapshot]:
        return [s for s in self.store.snapshots.values() if s.operator_id == operator_id]


class MemoryRunRepository(RunRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Run:
        return _get(self.store.runs, "run", id)

    async def add(self, run: Run) -> None:
        self.store.runs[run.id] = run

    async def list(self, project_id: Id, limit: int = 50) -> Sequence[Run]:
        runs = _in_project(self.store.runs, project_id)
        return sorted(runs, key=lambda run: run.started_at, reverse=True)[:limit]

    async def fix_snapshot(self, run_id: Id, operator_id: OperatorId, snapshot_id: Id) -> Run:
        run = await self.get(run_id)
        if operator_id in run.snapshots:
            return run
        fixed = run.model_copy(update={"snapshots": {**run.snapshots, operator_id: snapshot_id}})
        self.store.runs[run_id] = fixed
        return fixed


class MemoryWidgetRepository(WidgetRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Widget:
        return _get(self.store.widgets, "widget", id)

    async def add(self, widget: Widget) -> None:
        self.store.widgets[widget.id] = widget

    async def list(self, project_id: Id) -> Sequence[Widget]:
        return _in_project(self.store.widgets, project_id)

    async def list_by_session(self, session_id: Id) -> Sequence[Widget]:
        return [w for w in self.store.widgets.values() if w.session_id == session_id]


class MemoryDashboardRepository(DashboardRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Dashboard:
        return _get(self.store.dashboards, "dashboard", id)

    async def list(self, project_id: Id) -> Sequence[Dashboard]:
        return _in_project(self.store.dashboards, project_id)

    async def add(self, dashboard: Dashboard) -> None:
        self.store.dashboards[dashboard.id] = dashboard

    async def update(self, dashboard: Dashboard, expected_revision: int) -> Dashboard:
        return _update(self.store.dashboards, "dashboard", dashboard, expected_revision)

    async def add_version(self, version: DashboardVersion) -> None:
        await self.get(version.dashboard_id)
        self.store.dashboard_versions[version.id] = version

    async def get_version(self, id: Id) -> DashboardVersion:
        return _get(self.store.dashboard_versions, "dashboard version", id)

    async def versions(self, dashboard_id: Id) -> Sequence[DashboardVersion]:
        versions = [
            v for v in self.store.dashboard_versions.values() if v.dashboard_id == dashboard_id
        ]
        return sorted(versions, key=lambda version: version.number)


class MemoryTemplateRepository(TemplateRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Template:
        return _get(self.store.templates, "template", id)

    async def list(self, project_id: Id) -> Sequence[Template]:
        return _in_project(self.store.templates, project_id)

    async def add(self, template: Template) -> None:
        self.store.templates[template.id] = template

    async def update(self, template: Template, expected_revision: int) -> Template:
        return _update(self.store.templates, "template", template, expected_revision)


class MemoryReportRepository(ReportRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Report:
        return _get(self.store.reports, "report", id)

    async def list(self, project_id: Id) -> Sequence[Report]:
        return _in_project(self.store.reports, project_id)

    async def add(self, report: Report) -> None:
        self.store.reports[report.id] = report

    async def update(self, report: Report, expected_revision: int) -> Report:
        return _update(self.store.reports, "report", report, expected_revision)

    async def add_version(self, version: ReportVersion) -> None:
        await self.get(version.report_id)
        self.store.report_versions[version.id] = version

    async def get_version(self, id: Id) -> ReportVersion:
        return _get(self.store.report_versions, "report version", id)

    async def versions(self, report_id: Id) -> Sequence[ReportVersion]:
        return [v for v in self.store.report_versions.values() if v.report_id == report_id]


class MemoryAlertRuleRepository(AlertRuleRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> AlertRule:
        return _get(self.store.alert_rules, "alert rule", id)

    async def list(self, dashboard_id: Id) -> Sequence[AlertRule]:
        return [r for r in self.store.alert_rules.values() if r.dashboard_id == dashboard_id]

    async def list_enabled(self) -> Sequence[AlertRule]:
        return [r for r in self.store.alert_rules.values() if r.enabled]

    async def add(self, rule: AlertRule) -> None:
        self.store.alert_rules[rule.id] = rule

    async def update(self, rule: AlertRule, expected_revision: int) -> AlertRule:
        return _update(self.store.alert_rules, "alert rule", rule, expected_revision)

    async def record_check(self, id: Id, at: datetime) -> None:
        rule = await self.get(id)
        self.store.alert_rules[id] = rule.model_copy(update={"last_checked_at": at})


class MemoryAlertRepository(AlertRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> Alert:
        return _get(self.store.alerts, "alert", id)

    async def add(self, alert: Alert) -> None:
        self.store.alerts[alert.id] = alert

    async def save(self, alert: Alert) -> None:
        await self.get(alert.id)
        self.store.alerts[alert.id] = alert

    async def find(self, rule_id: Id, key: JsonObject) -> Alert | None:
        for alert in self.store.alerts.values():
            if alert.rule_id == rule_id and alert.key == key and alert.state is AlertState.FIRING:
                return alert
        return None

    async def list(self, project_id: Id, state: AlertState | None = None) -> Sequence[Alert]:
        alerts = [
            alert
            for alert in _in_project(self.store.alerts, project_id)
            if state is None or alert.state is state
        ]
        return sorted(alerts, key=lambda alert: alert.started_at, reverse=True)


class MemorySourceLocks(SourceLocks):
    """Memory writes at once and has no unique index for two fetches to collide on, so
    there is nothing to wait for."""

    async def hold(self, id: Id) -> None:
        return None


class MemorySourceCheckLog(SourceCheckLog):
    """Memory has no transactions; recording goes straight to the store."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def record_failure(
        self, id: Id, at: datetime, probe_token: str | None, error: str
    ) -> None:
        await MemoryDataSourceRepository(self.store).record_check(id, at, probe_token, error)
