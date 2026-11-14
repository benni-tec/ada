from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import Context, Session, SessionEntry


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
        the dashboard and shows it beside the conversation, else a new one titled
        "<dashboard name> (agent)". The flag says whether it was created."""
        ...

    async def show_dashboard(
        self, id: Id, dashboard_id: Id | None, expected_revision: int
    ) -> Session:
        """Put a dashboard in the panel beside the conversation, or clear the panel."""
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
