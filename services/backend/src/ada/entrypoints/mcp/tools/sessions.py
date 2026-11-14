from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id
from ada.core.models.sessions import Session
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def create_session(
        project_id: Id, title: str, service: FromDishka[SessionService]
    ) -> Session:
        """Start a session in a project: the record people see in the frontend while you
        work. Create one at the start of an analysis, then pass its id as `session_id`
        to the tools that add operators and widgets, so that everything you do shows up
        there with your note. Returns the session with its id."""
        return await service.create(project_id, title)
