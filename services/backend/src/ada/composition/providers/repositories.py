from dishka import Provider, Scope, provide

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
    """Where definitions are kept. In memory until the database repositories exist; each
    binding below is then replaced by its SQLAlchemy implementation, which takes the
    request's AsyncSession."""

    scope = Scope.REQUEST

    store = provide(MemoryStore, scope=Scope.APP)

    projects = provide(MemoryProjectRepository, provides=ProjectRepository)
    data_sources = provide(MemoryDataSourceRepository, provides=DataSourceRepository)
    sessions = provide(MemorySessionRepository, provides=SessionRepository)
    operators = provide(MemoryOperatorRepository, provides=OperatorRepository)
    snapshots = provide(MemorySnapshotRepository, provides=SnapshotRepository)
    runs = provide(MemoryRunRepository, provides=RunRepository)
    widgets = provide(MemoryWidgetRepository, provides=WidgetRepository)
    dashboards = provide(MemoryDashboardRepository, provides=DashboardRepository)
    templates = provide(MemoryTemplateRepository, provides=TemplateRepository)
    reports = provide(MemoryReportRepository, provides=ReportRepository)
    alert_rules = provide(MemoryAlertRuleRepository, provides=AlertRuleRepository)
    alerts = provide(MemoryAlertRepository, provides=AlertRepository)


provider = RepositoryProvider()
