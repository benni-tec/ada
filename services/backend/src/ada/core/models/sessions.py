from datetime import datetime
from enum import StrEnum

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id


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
    revision: int = 1


class EntryKind(StrEnum):
    # A message of a conversation that happened inside the platform.
    MESSAGE = "message"
    # A tool call that added an operator.
    OPERATOR = "operator"
    # A widget shown in the session.
    WIDGET = "widget"


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
