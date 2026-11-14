from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.health import Health
from ada.core.services.ports.system import SystemStatusService
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def system_status(service: FromDishka[SystemStatusService]) -> Health:
        """Report whether the ADA backend, database, queue, worker and analysis store are up."""
        return await service.health()
