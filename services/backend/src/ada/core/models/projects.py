from datetime import datetime

from ada.core.models.base import DomainModel, Id


class Project(DomainModel):
    """The top-level container. Everything else belongs to exactly one project."""

    id: Id
    name: str
    created_at: datetime
    revision: int = 1
