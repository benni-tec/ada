from collections.abc import Sequence
from typing import Protocol

from ada.core.models.base import Id
from ada.core.models.projects import Project


class ProjectService(Protocol):
    async def create(self, name: str) -> Project: ...
    async def get(self, id: Id) -> Project: ...
    async def list(self) -> Sequence[Project]: ...
    async def update(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        agent_instructions: str | None = None,
    ) -> Project:
        """Rename it, set the session agent's instructions for it ("" for none), or both;
        None keeps a field."""
        ...
