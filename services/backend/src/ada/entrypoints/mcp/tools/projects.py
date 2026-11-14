from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.projects import Project
from ada.core.services.ports.projects import ProjectService
from ada.entrypoints.mcp.injection import Inject


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def list_projects(service: FromDishka[ProjectService]) -> Sequence[Project]:
        """List every project. Call this first to find the project to work in; all other
        tools take a project id. Returns each project's id, name and revision."""
        return await service.list()

    @mcp.tool
    @inject
    async def create_project(name: str, service: FromDishka[ProjectService]) -> Project:
        """Create a project, the container for data sources, pipelines, sessions and
        widgets. Use it when no existing project fits the work; check list_projects first.
        Returns the new project with its id."""
        return await service.create(name)
