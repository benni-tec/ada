from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from ada.adapters.sources.files import LocalFileStore
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.config import Settings
from ada.core.models.agents import ResearchLimits
from ada.core.ports.agents import ResearchCalls
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    SnapshotRepository,
)
from ada.core.ports.secrets import SecretBox
from ada.core.ports.sources import FileStore, SourceCheckLog, SourceLocks, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer
from ada.core.services.agents.research import ResearchReaders
from ada.core.services.ports.refreshes import RefreshService
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources
from ada.core.services.sources.waiting import WaitingRefreshes


class SourceProvider(Provider):
    """Readers for each access kind, and registering and refreshing data sources."""

    @provide(scope=Scope.APP)
    def files(self, settings: Settings) -> FileStore:
        return LocalFileStore(settings.data_dir)

    @provide(scope=Scope.APP)
    async def readers(
        self,
        clock: Clock,
        files: FileStore,
        settings: Settings,
        web_budget: WebBudget,
        calls: ResearchCalls,
        limits: ResearchLimits,
    ) -> AsyncIterator[SourceReaders]:
        # One HTTP client for the process, so its connections are pooled; it is closed with
        # the container. Kept out of the container itself, so nothing else picks it up.
        key = settings.context_dev_api_key
        async with create_client(allow_private=settings.allow_private_sources) as client:
            # A research turn's paid reads count against its web calls.
            http = HttpSourceReaders(
                client,
                clock,
                files,
                key.get_secret_value() if key else None,
                web_budget,
                settings.web_daily_credit_limit,
                allow_private=settings.allow_private_sources,
                max_bytes=settings.source_max_bytes,
            )
            yield ResearchReaders(http, calls, limits)

    refreshes = provide(WaitingRefreshes, provides=RefreshService, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    def sources(
        self,
        projects: ProjectRepository,
        sources: DataSourceRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        readers: SourceReaders,
        checks: SourceCheckLog,
        store: AnalysisStore,
        events: EventPublisher,
        clock: Clock,
        locks: SourceLocks,
        explorer: WebExplorer,
        secrets: SecretBox,
        settings: Settings,
    ) -> SourceService:
        return DataSources(
            projects,
            sources,
            operators,
            snapshots,
            readers,
            checks,
            store,
            events,
            clock,
            locks,
            explorer,
            secrets,
            settings.ada_public_url,
        )


provider = SourceProvider()
