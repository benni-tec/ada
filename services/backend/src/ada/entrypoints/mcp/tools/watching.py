from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id
from ada.core.models.sources import CheckEvery, DataSource
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def watch_source(
        session_id: SessionId,
        source_id: Id,
        service: FromDishka[SourceService],
        check_every: CheckEvery | None = None,
    ) -> DataSource:
        """Watch a source's web page: Context.dev checks it on a schedule and, when it changed,
        ADA refreshes the source (and so its alert rules). Sets the source's freshness to
        push. For a source whose address is an http(s) page or file, typically a web
        source; each refresh it triggers reads the page again and spends the project's web
        credits. Watching a watched source replaces its monitor.
        Omit check_every for the server default.
        Choose 10min only for updates the user needs within minutes (e.g. shortage lists),
        hourly for news and lists changing during the day, daily for slow pages."""
        return await service.watch(source_id, check_every)

    @mcp.tool
    @inject
    async def unwatch_source(
        session_id: SessionId, source_id: Id, service: FromDishka[SourceService]
    ) -> DataSource:
        """Stop watching a source's page and set its freshness back to manual."""
        return await service.unwatch(source_id)
