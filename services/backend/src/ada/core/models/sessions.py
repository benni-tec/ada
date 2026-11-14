from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import OperatorId


class SessionAgent(StrEnum):
    # An ordinary session, led by the person's agent.
    SESSION = "session"
    # A child session in which the research agent runs.
    RESEARCH = "research"


class Session(DomainModel):
    """Exploratory work led by an agent. Belongs to a project, not to a user."""

    id: Id
    project_id: Id
    title: str
    # The dashboard it was started from, if any.
    origin_dashboard_id: Id | None = None
    # The dashboard shown beside the conversation, if any.
    panel_dashboard_id: Id | None = None
    created_at: datetime
    # Which agent works in it.
    agent: SessionAgent = SessionAgent.SESSION
    # The session that delegated to this one; None for a session of its own.
    parent_session_id: Id | None = None
    revision: int = 1


class EntryKind(StrEnum):
    # A message of a conversation that happened inside the platform.
    MESSAGE = "message"
    # A tool call that added an operator.
    OPERATOR = "operator"
    # A widget shown in the session.
    WIDGET = "widget"
    # The in-platform agent's answer to a message; `ref` is the AgentTurn's id. Added when
    # the turn is queued, so the record orders it right after the message it answers.
    AGENT_TURN = "agent_turn"
    # An MCP tool call of an external agent, whatever it did; `tool_call` says which. The
    # in-platform agent's calls are in its turn instead.
    TOOL_CALL = "tool_call"
    # The agent handed work to a child session; `ref` is its id.
    DELEGATION = "delegation"
    # What a child session came back with; `ref` is its id and `text` the report.
    REPORT = "report"


class ToolCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class ToolCall(DomainModel):
    """One tool call as the session shows it: the arguments shortened (see
    ada.core.services.sessions.shortened), the outcome and how long it took."""

    tool: str
    arguments: JsonObject
    status: ToolCallStatus
    # The tool error's message when it failed.
    error: str | None = None
    duration_ms: int


class PipelineContext(DomainModel):
    """A message about a pipeline: the agent builds on this operator."""

    kind: Literal["pipeline"] = "pipeline"
    operator_id: OperatorId


class DashboardContext(DomainModel):
    """A message about a dashboard: what the agent makes goes there, into `slot` if named."""

    kind: Literal["dashboard"] = "dashboard"
    dashboard_id: Id
    slot: str | None = None


class WidgetContext(DomainModel):
    """A message about a widget the person points at."""

    kind: Literal["widget"] = "widget"
    widget_id: Id


# What a message is about, besides its text: the chips of the chat input.
type Context = Annotated[
    PipelineContext | DashboardContext | WidgetContext, Field(discriminator="kind")
]


class SessionEntry(DomainModel):
    """One item in a session's record, in order. A session is this record, not a chat
    transcript: an external agent's tool calls land here although its conversation
    happens elsewhere."""

    id: Id
    session_id: Id
    kind: EntryKind
    # The message text, or the calling agent's one-line reason for a tool call.
    text: str = ""
    # The operator id or widget id the entry is about.
    ref: str | None = None
    actor: Actor
    created_at: datetime
    # For a message: what it is about (a pipeline, a dashboard and slot, a widget).
    context: tuple[Context, ...] = ()
    # For a tool call: which tool, with what, and how it went.
    tool_call: ToolCall | None = None
