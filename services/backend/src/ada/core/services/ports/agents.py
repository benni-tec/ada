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
from ada.core.models.sessions import Context, Session, SessionEntry
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
        commits. `model` picks another configured model than the session agent; a
        research session's turns default to the research agent."""
        ...

    async def post_report(self, child_session_id: Id, text: str, actor: Actor) -> PostedMessage:
        """Add a research session's report to its parent. When an agent delegated the
        research, the report also queues the parent's turn, as a message would; when a
        person did, it is only added to the record."""
        ...

    async def wait(self, id: Id) -> None:
        """Return once the earlier turns of the turn's session have ended, or at once when
        the turn is no longer queued: the session's turns run one after the other. A turn
        ahead that holds the session up for longer than a turn may run is failed first, so
        two turns of a session never run at once."""
        ...

    async def ended(self, id: Id) -> None:
        """Announce a turn that ended without `run` ending it (it could not be queued, or
        it was failed after its worker stopped): that it finished, and for a research turn
        what `run` would report into the parent session."""
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

    async def set_research_agent(
        self, model_id: str | None, expected_revision: int
    ) -> AgentSettingsView:
        """None lets research sessions use the session agent. The model must be
        configured."""
        ...


class ResearchService(Protocol):
    """Research delegated to the research agent, which works in a child session and
    reports back into the session that delegated."""

    async def delegate(
        self, parent_session_id: Id, brief: str, title: str, actor: Actor
    ) -> Session:
        """Create the research session, note the delegation in the parent and queue the
        research agent's turn on the brief. Returns at once."""
        ...

    async def report(
        self,
        child_session_id: Id,
        summary: str,
        source_ids: Sequence[Id],
        missing: Sequence[str],
        actor: Actor,
    ) -> SessionEntry:
        """Post the research session's report into its parent: the summary, the sources
        it added by name and what it could not find."""
        ...

    async def use_web_call(self, session_id: Id) -> None:
        """Count a paid web call about to be made for the session, committed at once, so a
        call that then fails counts too. A research session past its cap raises Invalid,
        telling the agent to report back; other sessions are not capped."""
        ...
