"""Repositories that keep everything in process memory.

They implement the repository ports exactly, including NotFound and the revision check,
so services can be built and tested before the database repositories exist, and tests of
anything above the ports need no database. Nothing here survives a restart.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ada.core.models.agents import (
    AgentSettings,
    AgentTurn,
    LlmModel,
    LlmProvider,
    TurnPart,
    TurnStatus,
)
from ada.core.models.alerts import Alert, AlertRule, AlertState
from ada.core.models.base import UNCHANGED, Change, DomainModel, Id, JsonObject
from ada.core.models.dashboards import Dashboard, DashboardVersion
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.operators import Operator, OperatorId, OperatorKind
from ada.core.models.projects import Project
from ada.core.models.reports import Report, ReportVersion, Template
from ada.core.models.runs import Run, Snapshot
from ada.core.models.sessions import Session, SessionEntry
from ada.core.models.sources import DataSource
from ada.core.models.widgets import Widget
from ada.core.ports.agents import TurnProgress
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    AgentTurnRepository,
    AlertRepository,
    AlertRuleRepository,
    DashboardRepository,
    DataSourceRepository,
    LlmModelRepository,
    LlmProviderRepository,
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
        self.agent_turns: dict[Id, AgentTurn] = {}
        self.cancel_requests: set[Id] = set()
        self.llm_providers: dict[Id, LlmProvider] = {}
        # Provider id -> the encrypted key.
        self.llm_api_keys: dict[Id, str] = {}
        # By (provider id, model); the stored id is recomputed from the provider's name.
        self.llm_models: dict[tuple[Id, str], LlmModel] = {}
        self.agent_settings = AgentSettings()
        # The session agent as (provider id, model), so it follows a renamed provider and
        # is gone with its model, as the database's SET NULL has it.
        self.session_agent: tuple[Id, str] | None = None
        self.research_agent: tuple[Id, str] | None = None
        # Source id -> the sealed secret of its monitor.
        self.monitor_secrets: dict[Id, str] = {}


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

    async def set_monitor(
        self, id: Id, monitor_id: str | None, secret_encrypted: str | None
    ) -> None:
        source = await self.get(id)
        self.store.data_sources[id] = source.model_copy(update={"monitor_id": monitor_id})
        if secret_encrypted is None:
            self.store.monitor_secrets.pop(id, None)
        else:
            self.store.monitor_secrets[id] = secret_encrypted

    async def monitor_secret_encrypted(self, id: Id) -> str | None:
        await self.get(id)
        return self.store.monitor_secrets.get(id)


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


class MemoryAgentTurnRepository(AgentTurnRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self, id: Id) -> AgentTurn:
        return _get(self.store.agent_turns, "agent turn", id)

    async def add(self, turn: AgentTurn) -> None:
        await MemorySessionRepository(self.store).get(turn.session_id)
        self.store.agent_turns[turn.id] = turn

    async def list(self, session_id: Id) -> Sequence[AgentTurn]:
        return [t for t in self.store.agent_turns.values() if t.session_id == session_id]

    async def start(self, id: Id) -> bool:
        turn = await self.get(id)
        if turn.status is not TurnStatus.QUEUED:
            return False
        self.store.agent_turns[id] = turn.model_copy(update={"status": TurnStatus.RUNNING})
        return True

    async def save_parts(self, id: Id, parts: Sequence[TurnPart]) -> None:
        turn = await self.get(id)
        self.store.agent_turns[id] = turn.model_copy(update={"parts": tuple(parts)})

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn:
        turn = (await self.get(id)).model_copy(
            update={"status": status, "parts": tuple(parts), "error": error, "finished_at": at}
        )
        self.store.agent_turns[id] = turn
        return turn

    async def request_cancel(self, id: Id, at: datetime) -> AgentTurn:
        turn = await self.get(id)
        if turn.status is TurnStatus.QUEUED:
            self.store.cancel_requests.add(id)
            turn = turn.model_copy(update={"status": TurnStatus.CANCELLED, "finished_at": at})
            self.store.agent_turns[id] = turn
        elif turn.status is TurnStatus.RUNNING:
            self.store.cancel_requests.add(id)
        return turn

    async def cancel_requested(self, id: Id) -> bool:
        await self.get(id)
        return id in self.store.cancel_requests


class MemoryTurnProgress(TurnProgress):
    """Memory has no transactions; progress goes straight to the store."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def start(self, id: Id) -> bool:
        return await MemoryAgentTurnRepository(self.store).start(id)

    async def checkpoint(self, id: Id, parts: Sequence[TurnPart]) -> bool:
        turns = MemoryAgentTurnRepository(self.store)
        await turns.save_parts(id, parts)
        return await turns.cancel_requested(id)

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn:
        return await MemoryAgentTurnRepository(self.store).finish(id, status, parts, error, at)


class MemoryLlmProviderRepository(LlmProviderRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def _stored(self, provider: LlmProvider) -> LlmProvider:
        has_key = provider.id in self.store.llm_api_keys
        return provider.model_copy(update={"has_api_key": has_key})

    async def get(self, id: Id) -> LlmProvider:
        return self._stored(_get(self.store.llm_providers, "llm provider", id))

    async def list(self) -> Sequence[LlmProvider]:
        return [self._stored(p) for p in self.store.llm_providers.values()]

    async def add(self, provider: LlmProvider, api_key: str | None) -> LlmProvider:
        self.store.llm_providers[provider.id] = provider
        if api_key is not None:
            self.store.llm_api_keys[provider.id] = api_key
        return self._stored(provider)

    async def update(
        self,
        provider: LlmProvider,
        expected_revision: int,
        api_key: Change[str | None] = UNCHANGED,
    ) -> LlmProvider:
        updated = _update(self.store.llm_providers, "llm provider", provider, expected_revision)
        if api_key is None:
            self.store.llm_api_keys.pop(provider.id, None)
        elif api_key is not UNCHANGED:
            self.store.llm_api_keys[provider.id] = api_key
        return self._stored(updated)

    async def delete(self, id: Id) -> None:
        _get(self.store.llm_providers, "llm provider", id)
        del self.store.llm_providers[id]
        self.store.llm_api_keys.pop(id, None)
        for key in [key for key in self.store.llm_models if key[0] == id]:
            del self.store.llm_models[key]

    async def api_key(self, id: Id) -> str | None:
        _get(self.store.llm_providers, "llm provider", id)
        return self.store.llm_api_keys.get(id)


def _model_id(store: MemoryStore, provider_id: Id, model: str) -> str:
    return f"{store.llm_providers[provider_id].name}/{model}"


def _model_key(store: MemoryStore, id: str) -> tuple[Id, str]:
    """The (provider id, model) of a model id; NotFound when there is no such model."""
    provider_name, _, model = id.partition("/")
    for provider in store.llm_providers.values():
        if provider.name == provider_name and (provider.id, model) in store.llm_models:
            return provider.id, model
    raise NotFound("model", id)


class MemoryLlmModelRepository(LlmModelRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def _current(self, key: tuple[Id, str]) -> LlmModel:
        model = self.store.llm_models[key]
        return model.model_copy(update={"id": _model_id(self.store, *key)})

    async def get(self, id: str) -> LlmModel:
        return self._current(_model_key(self.store, id))

    async def list(self) -> Sequence[LlmModel]:
        return [self._current(key) for key in self.store.llm_models]

    async def add(self, model: LlmModel) -> LlmModel:
        _get(self.store.llm_providers, "llm provider", model.provider_id)
        key = (model.provider_id, model.model)
        self.store.llm_models[key] = model
        return self._current(key)

    async def delete(self, id: str) -> None:
        del self.store.llm_models[_model_key(self.store, id)]


class MemoryAgentSettingsRepository(AgentSettingsRepository):
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def get(self) -> AgentSettings:
        return self.store.agent_settings.model_copy(
            update={
                "session_agent": self._current(self.store.session_agent),
                "research_agent": self._current(self.store.research_agent),
            }
        )

    def _current(self, ref: tuple[Id, str] | None) -> str | None:
        if ref is None or ref not in self.store.llm_models:
            return None
        return _model_id(self.store, *ref)

    async def update(self, settings: AgentSettings, expected_revision: int) -> AgentSettings:
        actual = self.store.agent_settings.revision
        if actual != expected_revision:
            raise Conflict("agent settings", 1, expected_revision, actual)
        self.store.session_agent = self._key(settings.session_agent)
        self.store.research_agent = self._key(settings.research_agent)
        self.store.agent_settings = AgentSettings(revision=expected_revision + 1)
        return await self.get()

    def _key(self, model_id: str | None) -> tuple[Id, str] | None:
        return _model_key(self.store, model_id) if model_id is not None else None
