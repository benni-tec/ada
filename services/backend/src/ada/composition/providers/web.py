from collections.abc import AsyncIterator
from typing import NewType

import httpx
from dishka import Provider, Scope, provide

from ada.adapters.sources.http import create_client
from ada.adapters.web.context import ContextPages
from ada.adapters.web.exa import ExaSearch
from ada.config import Settings
from ada.core.ports.web import PageReader, WebSearch

# Its own type, so nothing else in the container picks up the web tools' client.
WebClient = NewType("WebClient", httpx.AsyncClient)


class WebProvider(Provider):
    """Exa search and Context.dev page reading. A missing key does not fail startup; the
    tool that needs it fails with a message naming the setting."""

    @provide(scope=Scope.APP)
    async def client(self) -> AsyncIterator[WebClient]:
        async with create_client() as client:
            yield WebClient(client)

    @provide(scope=Scope.APP)
    def search(self, client: WebClient, settings: Settings) -> WebSearch:
        return ExaSearch(client, settings.exa_api_key)

    @provide(scope=Scope.APP)
    def pages(self, client: WebClient, settings: Settings) -> PageReader:
        return ContextPages(client, settings.context_api_key)


provider = WebProvider()
