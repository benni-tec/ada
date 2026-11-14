from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from ada.adapters.sources.files import LocalFileStore
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.config import Settings
from ada.core.ports.sources import FileStore, SourceReaders
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget
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
        self, clock: Clock, files: FileStore, settings: Settings, web_budget: WebBudget
    ) -> AsyncIterator[SourceReaders]:
        # One HTTP client for the process, so its connections are pooled; it is closed with
        # the container. Kept out of the container itself, so nothing else picks it up.
        key = settings.context_dev_api_key
        async with create_client() as client:
            yield HttpSourceReaders(
                client,
                clock,
                files,
                key.get_secret_value() if key else None,
                web_budget,
                settings.web_daily_credit_limit,
            )

    sources = provide(DataSources, provides=SourceService, scope=Scope.REQUEST)
    refreshes = provide(WaitingRefreshes, provides=RefreshService, scope=Scope.REQUEST)


provider = SourceProvider()
