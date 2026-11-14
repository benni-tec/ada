from dishka import Provider, Scope, provide

from ada.composition.unbuilt import unbuilt
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.sources import SourceService


class SourceProvider(Provider):
    """Readers for each access kind, and registering and refreshing data sources."""

    readers = provide(unbuilt(SourceReaders), scope=Scope.APP)
    sources = provide(unbuilt(SourceService), scope=Scope.REQUEST)


provider = SourceProvider()
