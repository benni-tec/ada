from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.ports.sources import SourceReaders
from ada.core.ports.system import Clock
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources


class SourceProvider(Provider):
    """Readers for each access kind, and registering and refreshing data sources."""

    @provide(scope=Scope.APP)
    async def readers(self, clock: Clock) -> AsyncIterator[SourceReaders]:
        # One HTTP client for the process, so its connections are pooled; it is closed with
        # the container. Kept out of the container itself, so nothing else picks it up.
        async with create_client() as client:
            yield HttpSourceReaders(client, clock)

    sources = provide(DataSources, provides=SourceService, scope=Scope.REQUEST)


provider = SourceProvider()
