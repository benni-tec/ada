from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

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
from ada.core.ports.sources import SourceCheckLog, SourceLocks, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import PageReader
from ada.core.services.agents.research import ResearchPages
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources


class SourceProvider(Provider):
    """Readers for each access kind, and registering and refreshing data sources."""

    @provide(scope=Scope.APP)
    async def readers(
        self, clock: Clock, pages: PageReader, calls: ResearchCalls, limits: ResearchLimits
    ) -> AsyncIterator[SourceReaders]:
        # One HTTP client for the process, so its connections are pooled; it is closed with
        # the container. Kept out of the container itself, so nothing else picks it up.
        async with create_client() as client:
            yield HttpSourceReaders(client, clock, ResearchPages(pages, calls, limits))

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
        pages: PageReader,
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
            pages,
            secrets,
            settings.ada_public_url,
        )


provider = SourceProvider()
