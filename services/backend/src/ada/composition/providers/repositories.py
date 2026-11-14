from dishka import Provider, Scope, provide

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


provider = RepositoryProvider()
