from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.agents import (
    AgentSettingsView,
    AgentTurn,
    LlmProvider,
    ModelInfo,
    ModelList,
    PostedMessage,
    ProviderKind,
)
from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.sessions import Context
from ada.core.ports.agents import AgentToolbox


class AgentTurnService(Protocol):
    """Messages to the in-platform agent and its answers."""

    async def models(self) -> ModelList:
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


class AgentSettingsService(Protocol):
    """The agent's configuration, shared by all projects: model providers with their API
    keys (stored encrypted, never returned), their models, and the session agent."""

    async def view(self) -> AgentSettingsView: ...

    async def add_provider(
        self, name: str, kind: ProviderKind, base_url: str | None = None, api_key: str | None = None
    ) -> LlmProvider:
        """`name` is a slug, unique. An empty `api_key` is none. Storing a key without a
        master key raises NotConfigured."""
        ...

    async def update_provider(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        kind: ProviderKind | None = None,
        base_url: Change[str | None] = UNCHANGED,
        api_key: Change[str | None] = UNCHANGED,
    ) -> LlmProvider:
        """None keeps name and kind; UNCHANGED keeps base URL and key, None or "" clears
        them. A new key never needs the old one."""
        ...

    async def delete_provider(self, id: Id) -> None:
        """With its models; the session agent is cleared when it was one of them."""
        ...

    async def add_model(self, provider_id: Id, model: str) -> ModelInfo: ...

    async def delete_model(self, id: str) -> None:
        """`id` is "<provider>/<model>"; the session agent is cleared when it was this one."""
        ...

    async def set_session_agent(
        self, model_id: str | None, expected_revision: int
    ) -> AgentSettingsView:
        """None leaves sessions without an agent. The model must be configured."""
        ...

    async def set_instructions(
        self, instructions: str, expected_revision: int
    ) -> AgentSettingsView:
        """The session agent's instructions for every project, added to its system prompt
        after ADA's own rules; "" for none. Shares the revision with the session agent."""
        ...
