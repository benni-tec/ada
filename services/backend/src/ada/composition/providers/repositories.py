from dishka import Provider, Scope, provide

from ada.adapters.db.agent_repositories import SqlAgentTurnRepository, SqlTurnProgress
from ada.adapters.db.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from ada.adapters.db.llm_repositories import (
    SqlAgentSettingsRepository,
    SqlLlmModelRepository,
    SqlLlmProviderRepository,
)
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
    SqlResearchCalls,
    SqlSessionRepository,
    SqlSourceCheckLog,
    SqlSourceLocks,
    SqlWidgetRepository,
)
from ada.core.ports.agents import ResearchCalls, TurnProgress
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


class RepositoryProvider(Provider):
    """Where definitions are kept: PostgreSQL, through the request's AsyncSession. The
    session is one per request and shared by all repositories of that request, so they
    write in one transaction (see providers/infrastructure.py)."""

    scope = Scope.REQUEST

    projects = provide(SqlProjectRepository, provides=ProjectRepository)
    data_sources = provide(SqlDataSourceRepository, provides=DataSourceRepository)
    sessions = provide(SqlSessionRepository, provides=SessionRepository)
    operators = provide(SqlOperatorRepository, provides=OperatorRepository)
    snapshots = provide(SqlSnapshotRepository, provides=SnapshotRepository)
    runs = provide(SqlRunRepository, provides=RunRepository)
    widgets = provide(SqlWidgetRepository, provides=WidgetRepository)
    dashboards = provide(SqlDashboardRepository, provides=DashboardRepository)
    templates = provide(SqlTemplateRepository, provides=TemplateRepository)
    reports = provide(SqlReportRepository, provides=ReportRepository)
    alert_rules = provide(SqlAlertRuleRepository, provides=AlertRuleRepository)
    alerts = provide(SqlAlertRepository, provides=AlertRepository)
    agent_turns = provide(SqlAgentTurnRepository, provides=AgentTurnRepository)
    llm_providers = provide(SqlLlmProviderRepository, provides=LlmProviderRepository)
    llm_models = provide(SqlLlmModelRepository, provides=LlmModelRepository)
    agent_settings = provide(SqlAgentSettingsRepository, provides=AgentSettingsRepository)

    source_locks = provide(SqlSourceLocks, provides=SourceLocks)
    # Its own connection per record, from the engine, not the request's session.
    source_checks = provide(SqlSourceCheckLog, provides=SourceCheckLog, scope=Scope.APP)
    # A running turn's progress, likewise on connections of its own.
    turn_progress = provide(SqlTurnProgress, provides=TurnProgress, scope=Scope.APP)
    # A research session's paid web calls, counted before each call and committed at once.
    research_calls = provide(SqlResearchCalls, provides=ResearchCalls, scope=Scope.APP)


provider = RepositoryProvider()
