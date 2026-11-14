from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id
from ada.core.models.sources import DataSource
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def watch_source(source_id: Id, service: FromDishka[SourceService]) -> DataSource:
        """Watch a source's web page: Context.dev checks it on a schedule and, when it
        changes, ada refreshes the source (and so its alert rules). Sets the source's
        freshness to push. Creating the monitor is one paid call; each refresh it triggers
        reads the page again. Watching a watched source replaces its monitor."""
        return await service.watch(source_id)

    @mcp.tool
    @inject
    async def unwatch_source(source_id: Id, service: FromDishka[SourceService]) -> DataSource:
        """Stop watching a source's page and set its freshness back to manual."""
        return await service.unwatch(source_id)
