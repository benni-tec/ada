from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.projects import Project
from ada.core.ports.repositories import ProjectRepository
from ada.core.ports.system import Clock
from ada.core.services.ports.projects import ProjectService


class Projects(ProjectService):
    def __init__(self, projects: ProjectRepository, clock: Clock) -> None:
        self.projects = projects
        self.clock = clock

    async def create(self, name: str) -> Project:
        project = Project(id=uuid7(), name=_name(name), created_at=self.clock.now())
        await self.projects.add(project)
        return project

    async def get(self, id: Id) -> Project:
        return await self.projects.get(id)

    async def list(self) -> Sequence[Project]:
        return await self.projects.list()

    async def rename(self, id: Id, name: str, expected_revision: int) -> Project:
        project = await self.projects.get(id)
        return await self.projects.update(
            project.model_copy(update={"name": _name(name)}), expected_revision
        )


def _name(name: str) -> str:
    # A blank name would leave the project unrecognisable in every list.
    name = name.strip()
    if not name:
        raise Invalid("A project needs a name")
    return name
