from datetime import datetime

from ada.core.models.base import DomainModel, Id


class Project(DomainModel):
    """The top-level container. Everything else belongs to exactly one project."""

    id: Id
    name: str
    created_at: datetime
    # Free text for the session agent in this project, added to its system prompt after
    # ADA's own rules and the instructions for every project; "" for none.
    agent_instructions: str = ""
    revision: int = 1
