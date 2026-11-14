from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.base import Id
from ada.core.models.projects import Project
from ada.core.services.ports.projects import ProjectService
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["projects"])


class NewProject(Request):
    name: str


class ProjectChange(Request):
    """Fields left out stay as they are."""

    expected_revision: int
    name: str | None = None
    # Free text for the session agent in this project, after ADA's own rules; "" for none.
    agent_instructions: str | None = None


@router.get("/projects")
async def list_projects(service: FromDishka[ProjectService]) -> Sequence[Project]:
    return await service.list()


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(body: NewProject, service: FromDishka[ProjectService]) -> Project:
    return await service.create(body.name)


@router.get("/projects/{project_id}")
async def get_project(project_id: Id, service: FromDishka[ProjectService]) -> Project:
    return await service.get(project_id)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: Id, body: ProjectChange, service: FromDishka[ProjectService]
) -> Project:
    """Rename it or set the session agent's instructions for it."""
    return await service.update(
        project_id,
        body.expected_revision,
        name=body.name,
        agent_instructions=body.agent_instructions,
    )
