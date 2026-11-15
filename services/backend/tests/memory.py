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
    MemoryAgentSettingsRepository,
    MemoryAgentTurnRepository,
    MemoryAlertRepository,
    MemoryAlertRuleRepository,
    MemoryAttachmentRepository,
    MemoryCaseRepository,
    MemoryDashboardRepository,
    MemoryDataSourceRepository,
    MemoryJudgeSettingsRepository,
    MemoryLlmModelRepository,
    MemoryLlmProviderRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemoryReportRepository,
    MemoryResearchCalls,
    MemoryRunRepository,
    MemorySessionRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemorySourceLocks,
    MemoryStatisticalModelRepository,
    MemoryStore,
    MemoryTemplateRepository,
    MemoryTurnProgress,
    MemoryWidgetRepository,
)
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.memory.web import MemoryWebBudget
from ada.core.ports.agents import ResearchCalls, TurnProgress
from ada.core.ports.events import EventBroadcaster, EventStream
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    AgentTurnRepository,
    AlertRepository,
    AlertRuleRepository,
    AttachmentRepository,
    CaseRepository,
    DashboardRepository,
    DataSourceRepository,
    JudgeSettingsRepository,
    LlmModelRepository,
    LlmProviderRepository,
    OperatorRepository,
    ProjectRepository,
    ReportRepository,
    RunRepository,
    SessionRepository,
    SnapshotRepository,
    StatisticalModelRepository,
    TemplateRepository,
    WidgetRepository,
)
from ada.core.ports.sources import SourceCheckLog, SourceLocks
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.web import WebBudget


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
    attachments = provide(MemoryAttachmentRepository, provides=AttachmentRepository)
    operators = provide(MemoryOperatorRepository, provides=OperatorRepository)
    snapshots = provide(MemorySnapshotRepository, provides=SnapshotRepository)
    runs = provide(MemoryRunRepository, provides=RunRepository)
    widgets = provide(MemoryWidgetRepository, provides=WidgetRepository)
    dashboards = provide(MemoryDashboardRepository, provides=DashboardRepository)
    templates = provide(MemoryTemplateRepository, provides=TemplateRepository)
    reports = provide(MemoryReportRepository, provides=ReportRepository)
    alert_rules = provide(MemoryAlertRuleRepository, provides=AlertRuleRepository)
    alerts = provide(MemoryAlertRepository, provides=AlertRepository)
    agent_turns = provide(MemoryAgentTurnRepository, provides=AgentTurnRepository)
    llm_providers = provide(MemoryLlmProviderRepository, provides=LlmProviderRepository)
    llm_models = provide(MemoryLlmModelRepository, provides=LlmModelRepository)
    agent_settings = provide(MemoryAgentSettingsRepository, provides=AgentSettingsRepository)
    judge_settings = provide(MemoryJudgeSettingsRepository, provides=JudgeSettingsRepository)
    statistical_models = provide(
        MemoryStatisticalModelRepository, provides=StatisticalModelRepository
    )
    cases = provide(MemoryCaseRepository, provides=CaseRepository)
    source_checks = provide(MemorySourceCheckLog, provides=SourceCheckLog, scope=Scope.APP)
    source_locks = provide(MemorySourceLocks, provides=SourceLocks, scope=Scope.APP)
    turn_progress = provide(MemoryTurnProgress, provides=TurnProgress, scope=Scope.APP)
    web_budget = provide(MemoryWebBudget, provides=WebBudget, scope=Scope.APP)
    research_calls = provide(MemoryResearchCalls, provides=ResearchCalls, scope=Scope.APP)


def memory_adapters() -> tuple[Provider, Provider]:
    """Both, for a test that needs no service at all."""
    return MemoryBackground(), MemoryRepositories()
