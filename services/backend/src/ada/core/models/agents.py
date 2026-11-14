"""The agent inside the platform: the models it may use, and its turns.

A turn is the agent's answer to one message of a session. It is stored as parts in the
order they happened (reasoning, tool calls with their arguments and results, the data
sources it read, text), the shape the frontend's Trace component renders.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.sessions import SessionEntry

# What a configured model is for. One for now; the operators of later waves add theirs.
SESSION_AGENT = "session_agent"


class ModelInfo(DomainModel):
    """A model from the models file. Its key is never part of it."""

    # "<provider>/<model>", e.g. "gemini/gemini-2.5-flash".
    id: str
    provider: str
    model: str
    # What the file names it for, e.g. "session_agent".
    purposes: tuple[str, ...] = ()
    # False when it cannot be used, e.g. its key's variable is not set; `reason` says why.
    available: bool
    reason: str | None = None


class ModelList(DomainModel):
    models: tuple[ModelInfo, ...] = ()
    # The model that answers messages in sessions and dashboard panels; None without one.
    session_agent: str | None = None


class TurnStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = frozenset({TurnStatus.DONE, TurnStatus.FAILED, TurnStatus.CANCELLED})


class ReasoningPart(DomainModel):
    type: Literal["reasoning"] = "reasoning"
    text: str


class ToolState(StrEnum):
    # The call is made; no result yet.
    INPUT_AVAILABLE = "input-available"
    OUTPUT_AVAILABLE = "output-available"
    OUTPUT_ERROR = "output-error"


class ToolPart(DomainModel):
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    state: ToolState
    input: JsonObject = {}
    output: Any = None
    error_text: str | None = None


class TextPart(DomainModel):
    type: Literal["text"] = "text"
    text: str


class SourcePart(DomainModel):
    """A data source the agent read, so the answer shows where its numbers come from."""

    type: Literal["source"] = "source"
    source_id: Id
    title: str
    url: str | None = None


type TurnPart = Annotated[
    ReasoningPart | ToolPart | TextPart | SourcePart, Field(discriminator="type")
]


class AgentTurn(DomainModel):
    """The agent's answer to one message. Written by the worker as it goes; no revision,
    since nobody else edits it (a cancel request is a flag of its own)."""

    id: Id
    session_id: Id
    # The message it answers.
    prompt_entry_id: Id
    # The model's id in the models file.
    model: str
    status: TurnStatus = TurnStatus.QUEUED
    parts: tuple[TurnPart, ...] = ()
    # Why it failed, readable by a person.
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class PostedMessage(DomainModel):
    entry: SessionEntry
    # None when no session agent is configured.
    turn: AgentTurn | None = None


class HistoryMessage(DomainModel):
    """An earlier message of the conversation, as the model is shown it."""

    role: Literal["user", "assistant"]
    text: str


class TurnRequest(DomainModel):
    """Everything a turn sends to the model, independent of the library that sends it."""

    model: str
    # The system prompt: what ADA is, the session, the rules and the message's context.
    instructions: str
    history: tuple[HistoryMessage, ...] = ()
    prompt: str
    # At most this many model requests; a turn that needs more fails.
    max_steps: int


class ToolSpec(DomainModel):
    """A tool the agent may call: one of the platform's MCP tools."""

    name: str
    description: str = ""
    input_schema: JsonObject = {}
