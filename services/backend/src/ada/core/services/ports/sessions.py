from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import Context, Session, SessionAgent, SessionEntry, ToolCall


class SessionService(Protocol):
    async def create(
        self, project_id: Id, title: str, origin_dashboard_id: Id | None = None
    ) -> Session: ...

    async def get(self, id: Id) -> Session: ...
    async def list(self, project_id: Id) -> Sequence[Session]: ...
    async def entries(self, session_id: Id) -> Sequence[SessionEntry]: ...

    async def rename(self, id: Id, title: str, expected_revision: int) -> Session: ...

    async def dashboard_agent_session(self, dashboard_id: Id) -> tuple[Session, bool]:
        """The session of a dashboard's agent panel: the newest session that started from
        the dashboard and has it attached, else a new one titled "<dashboard name>
        (agent)" with the dashboard attached. The flag says whether it was created."""
        ...

    # Each of these appends to the session's record and publishes an event.

    async def add_message(
        self, session_id: Id, text: str, actor: Actor, context: Sequence[Context] = ()
    ) -> SessionEntry:
        """A message, with what it is about. Every context item must exist in the session's
        project."""
        ...

    async def record_operator(
        self, session_id: Id, operator_id: OperatorId, note: str, actor: Actor
    ) -> SessionEntry: ...

    async def record_widget(
        self, session_id: Id, widget_id: Id, note: str, actor: Actor
    ) -> SessionEntry: ...

    async def record_agent_turn(self, session_id: Id, turn_id: Id, actor: Actor) -> SessionEntry:
        """Where the agent's answer to the latest message goes in the record."""
        ...

    async def record_tool_call(self, session_id: Id, call: ToolCall, actor: Actor) -> SessionEntry:
        """An external agent's tool call, its arguments shortened for the record."""
        ...

    async def check(self, session_id: Id, project_id: Id | None = None) -> Session:
        """The session a tool call works in: it must exist, and be in `project_id` when the
        call names a project (Invalid otherwise)."""
        ...

    async def create_child(
        self, parent_session_id: Id, title: str, agent: SessionAgent, actor: Actor
    ) -> Session:
        """A research or analysis session under the parent, in its project, and a
        delegation entry in the parent that names it. A delegated session does not delegate
        further."""
        ...

    async def record_report(self, child_session_id: Id, text: str, actor: Actor) -> SessionEntry:
        """What a research session came back with, as a report entry in its parent."""
        ...

    async def record_alert(self, session_id: Id, alert_id: Id, text: str) -> SessionEntry:
        """An alert of a rule attached to the session started or ended, as the platform
        saw it."""
        ...
