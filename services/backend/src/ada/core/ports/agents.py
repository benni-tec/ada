"""What the in-platform agent needs from the outside: the configured models, a library
that runs a model with tools, the tools themselves, and a place to write a running turn's
progress. The core names none of these libraries."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol

from ada.core.models.actors import Actor
from ada.core.models.agents import (
    AgentTurn,
    ModelList,
    ModelTarget,
    ToolSpec,
    TurnPart,
    TurnRequest,
    TurnStatus,
)
from ada.core.models.base import Id, JsonObject
from ada.core.models.sessions import SessionAgent


class AgentFailed(Exception):
    """A turn could not be completed: the provider is down, refused the key, the model kept
    calling tools wrongly, or it needed too many steps. The message is for a person."""


class ToolCallFailed(Exception):
    """A tool refused the call, e.g. SQL that does not parse. The message goes back to the
    model, which may correct itself."""


class LanguageModels(Protocol):
    """The configured models, as far as running the agent needs them."""

    async def catalog(self) -> ModelList:
        """Every configured model, whether each can be used, and the session agent."""
        ...

    async def research_agent(self) -> str | None:
        """The model that runs research sessions: the research agent, else the session
        agent; None without either."""
        ...

    async def target(self, model_id: str) -> ModelTarget:
        """What the runtime needs to call the model, its key decrypted. Raises Invalid,
        with the reason, when the model is not configured or cannot be used."""
        ...


class AgentTools(Protocol):
    """The tools of one turn, already acting as the agent in its session."""

    def specs(self) -> Sequence[ToolSpec]: ...

    async def call(self, name: str, arguments: JsonObject) -> Any:
        """The tool's result as JSON. Raises ToolCallFailed when the tool refused."""
        ...


class AgentToolbox(Protocol):
    """Opens the tools for a turn. The caller of a turn provides it: the tools are the
    platform's own MCP tools, which only an entrypoint can serve."""

    def connect(
        self, agent: Actor, session_id: Id, profile: SessionAgent = SessionAgent.SESSION
    ) -> AbstractAsyncContextManager[AgentTools]:
        """Tools that record what they do as `agent`, and that default to `session_id`
        where they take a session. `profile` picks the tools: the research agent gets
        fewer than the session agent."""
        ...


class TurnSink(Protocol):
    """Where a running turn reports its parts, as they happen."""

    async def add(self, part: TurnPart) -> int:
        """Append a part; returns its index."""
        ...

    async def replace(self, index: int, part: TurnPart) -> None:
        """A part moved on: text grew, a tool call got its result."""
        ...

    async def checkpoint(self) -> bool:
        """Called between steps: stores the parts so far, and returns True when the turn
        should stop because someone cancelled it."""
        ...


class AgentRuntime(Protocol):
    async def run(self, request: TurnRequest, tools: AgentTools, sink: TurnSink) -> TurnStatus:
        """Run the model with the tools until it answers (DONE) or the sink asks it to stop
        between two steps (CANCELLED). Raises AgentFailed with a readable reason."""
        ...


class TurnProgress(Protocol):
    """Writes of a running turn, each committed at once in a short transaction of its own.

    A turn runs for minutes. Written in the task's own transaction, its progress would stay
    invisible until the end, and the turn's row would stay locked, so a cancel request
    would wait for the turn it means to stop."""

    async def start(self, id: Id, at: datetime) -> bool:
        """As AgentTurnRepository.start."""
        ...

    async def checkpoint(self, id: Id, parts: Sequence[TurnPart]) -> bool:
        """Store the parts; True when the turn should stop: a cancel was requested
        meanwhile, or it no longer runs (and nothing is stored)."""
        ...

    async def running(self, id: Id) -> bool:
        """Whether the turn still runs. Asked before each tool call, so a worker whose turn
        was failed meanwhile changes nothing more."""
        ...

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn | None:
        """As AgentTurnRepository.finish."""
        ...

    async def session_turns(self, id: Id) -> Sequence[AgentTurn]:
        """The turns of turn `id`'s session, oldest first: read afresh at every call, by a
        turn waiting for the ones before it, without holding a connection meanwhile."""
        ...

    async def abandon(self, id: Id, error: str, at: datetime) -> AgentTurn | None:
        """End a turn that is still queued or running as failed, and flag it for cancelling,
        so a worker that still runs it after all stops at its next step. None when it has
        ended meanwhile."""
        ...


class ResearchCalls(Protocol):
    """The paid web calls of research sessions, each counted in a short transaction of its
    own, like TurnProgress.

    A web tool counts its call before it calls the provider. Counted in the tool call's own
    transaction, a call that fails or times out would roll its count back and escape the
    cap, and the session's row would stay locked, its connection held, for as long as the
    provider takes."""

    async def use(self, session_id: Id, cap: int) -> bool:
        """Count one call against a research session, committed when this returns. False,
        counting nothing, when it has made `cap` calls already. Other sessions are not
        capped or counted: True. NotFound for an unknown session."""
        ...
