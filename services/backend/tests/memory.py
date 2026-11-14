"""Providers that bind the in-memory adapters in place of PostgreSQL and Valkey.

The composition root binds the real adapters. A test that builds the app, the MCP server,
the worker or a container passes these, unless it means to use the real service:

- MemoryBackground: events and the task dispatcher, instead of Valkey.
- MemoryRepositories: the repositories, instead of PostgreSQL.

Events still go through the transactional publisher of the composition root, so they reach
the bus once the request's unit of work ends without an error.
"""

from dishka import Provider, Scope, provide

from ada.adapters.memory.events import MemoryEventBus
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
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.core.ports.events import EventBroadcaster, EventStream
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
from ada.core.ports.tasks import TaskDispatcher


class MemoryBackground(Provider):
    """One MemoryEventBus as broadcaster and stream, and a dispatcher that records."""

    scope = Scope.APP

    bus = provide(MemoryEventBus)
    dispatcher = provide(RecordingTaskDispatcher, provides=TaskDispatcher)

    @provide
    def broadcaster(self, bus: MemoryEventBus) -> EventBroadcaster:
        return bus

    @provide
    def stream(self, bus: MemoryEventBus) -> EventStream:
        return bus


class MemoryRepositories(Provider):
    """Every repository on one MemoryStore, shared across requests."""

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


def memory_adapters() -> tuple[Provider, Provider]:
    """Both, for a test that needs no service at all."""
    return MemoryBackground(), MemoryRepositories()
