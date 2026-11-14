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

    def connect(self, agent: Actor, session_id: Id) -> AbstractAsyncContextManager[AgentTools]:
        """Tools that record what they do as `agent`, and that default to `session_id`
        where they take a session."""
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

    async def start(self, id: Id) -> bool:
        """As AgentTurnRepository.start."""
        ...

    async def checkpoint(self, id: Id, parts: Sequence[TurnPart]) -> bool:
        """Store the parts; True when a cancel was requested meanwhile."""
        ...

    async def finish(
        self,
        id: Id,
        status: TurnStatus,
        parts: Sequence[TurnPart],
        error: str | None,
        at: datetime,
    ) -> AgentTurn: ...
