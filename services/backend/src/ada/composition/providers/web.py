from collections.abc import AsyncIterator
from typing import NewType

import httpx
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine

from ada.adapters.db.web_repositories import SqlWebBudget
from ada.adapters.sources.http import create_client
from ada.adapters.web.context_dev import ContextDevWeb
from ada.adapters.web.exa import ExaSearch
from ada.config import Settings
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer, WebSearch
from ada.core.services.exploration.web import WebExploration
from ada.core.services.ports.web import WebExplorationService

# Its own type, so nothing else in the container picks up the web's client.
WebClient = NewType("WebClient", httpx.AsyncClient)


class WebProvider(Provider):
    """Exa search and Context.dev on ADA's keys for the web tools and page monitors, and
    the projects' daily credits, which the web sources spend too (providers/sources.py).
    A missing key does not fail startup; what needs it refuses, naming the setting."""

    @provide(scope=Scope.APP)
    async def client(self) -> AsyncIterator[WebClient]:
        async with create_client() as client:
            yield WebClient(client)

    @provide(scope=Scope.APP)
    def search(self, client: WebClient, settings: Settings) -> WebSearch:
        return ExaSearch(client, settings.exa_api_key)

    @provide(scope=Scope.APP)
    def explorer(self, client: WebClient, settings: Settings) -> WebExplorer:
        key = settings.context_dev_api_key
        return ContextDevWeb(client, key.get_secret_value() if key else None)

    # Its own connection per write, from the engine, not the request's session.
    @provide(scope=Scope.APP)
    def budget(self, engine: AsyncEngine) -> WebBudget:
        return SqlWebBudget(engine)

    @provide(scope=Scope.REQUEST)
    def exploration(
        self,
        search: WebSearch,
        explorer: WebExplorer,
        budget: WebBudget,
        clock: Clock,
        settings: Settings,
    ) -> WebExplorationService:
        return WebExploration(search, explorer, budget, clock, settings.web_daily_credit_limit)


provider = WebProvider()
