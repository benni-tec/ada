from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.agents import AgentTurn, ModelList, PostedMessage
from ada.core.models.base import Id
from ada.core.models.sessions import Context
from ada.core.ports.agents import AgentToolbox


class AgentTurnService(Protocol):
    """Messages to the in-platform agent and its answers."""

    def models(self) -> ModelList:
        """The configured models, whether each can be used, and the session agent."""
        ...

    async def post_message(
        self,
        session_id: Id,
        text: str,
        actor: Actor,
        context: Sequence[Context] = (),
        model: str | None = None,
    ) -> PostedMessage:
        """Add a message to a session and, when a session agent is configured, queue its
        turn: the turn, an agent_turn entry after the message, and the task once this
        commits. `model` picks another configured model than the session agent."""
        ...

    async def turns(self, session_id: Id) -> Sequence[AgentTurn]:
        """Oldest first."""
        ...

    async def get(self, id: Id) -> AgentTurn: ...

    async def cancel(self, id: Id) -> AgentTurn:
        """Ask a turn to stop. A queued turn is cancelled at once; a running one stops at
        its next step. A finished turn is returned as it is."""
        ...

    async def run(self, id: Id, toolbox: AgentToolbox) -> AgentTurn:
        """Run a queued turn to its end with the tools the toolbox opens, publishing its
        parts as they happen. Never raises for the model's or the tools' failures: those
        end the turn as failed, with the reason."""
        ...
