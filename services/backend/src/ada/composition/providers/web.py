from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine

from ada.adapters.db.web_repositories import SqlWebBudget
from ada.adapters.sources.http import create_client
from ada.adapters.web.context_dev import ContextDevWeb
from ada.config import Settings
from ada.core.ports.repositories import SessionRepository
from ada.core.ports.system import Clock
from ada.core.ports.web import WebBudget, WebExplorer
from ada.core.services.exploration.web import WebExploration
from ada.core.services.ports.web import WebExplorationService


class WebProvider(Provider):
    """Context.dev on ADA's key for the web tools, and the projects' daily credits, which
    the web sources spend too (providers/sources.py)."""

    @provide(scope=Scope.APP)
    async def explorer(self, settings: Settings) -> AsyncIterator[WebExplorer]:
        key = settings.context_dev_api_key
        async with create_client() as client:
            yield ContextDevWeb(client, key.get_secret_value() if key else None)

    # Its own connection per write, from the engine, not the request's session.
    @provide(scope=Scope.APP)
    def budget(self, engine: AsyncEngine) -> WebBudget:
        return SqlWebBudget(engine)

    @provide(scope=Scope.REQUEST)
    def exploration(
        self,
        sessions: SessionRepository,
        explorer: WebExplorer,
        budget: WebBudget,
        clock: Clock,
        settings: Settings,
    ) -> WebExplorationService:
        return WebExploration(sessions, explorer, budget, clock, settings.web_daily_credit_limit)


provider = WebProvider()
