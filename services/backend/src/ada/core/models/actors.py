from enum import StrEnum

from ada.core.models.base import DomainModel


class ActorKind(StrEnum):
    USER = "user"
    # The agent that runs inside the platform.
    AGENT = "agent"
    # An agent in someone's own client, working over MCP.
    EXTERNAL_AGENT = "external_agent"
    # The platform itself, e.g. a scheduled refresh.
    SYSTEM = "system"


class Actor(DomainModel):
    """Who did something. There are no users yet, so this is a label, not an identity."""

    kind: ActorKind
    # For an external agent, the client name it reported when connecting over MCP.
    name: str


# The platform's own work: refreshes, source operators, alert checks and their filters.
PLATFORM = Actor(kind=ActorKind.SYSTEM, name="ada")
