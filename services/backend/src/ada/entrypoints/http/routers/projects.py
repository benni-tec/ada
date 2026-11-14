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


class ProjectRename(Request):
    name: str
    expected_revision: int


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
async def rename_project(
    project_id: Id, body: ProjectRename, service: FromDishka[ProjectService]
) -> Project:
    return await service.rename(project_id, body.name, body.expected_revision)
