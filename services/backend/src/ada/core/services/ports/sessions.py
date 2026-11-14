from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import Session, SessionEntry


class SessionService(Protocol):
    async def create(
        self, project_id: Id, title: str, origin_dashboard_id: Id | None = None
    ) -> Session: ...

    async def get(self, id: Id) -> Session: ...
    async def list(self, project_id: Id) -> Sequence[Session]: ...
    async def entries(self, session_id: Id) -> Sequence[SessionEntry]: ...

    async def rename(self, id: Id, title: str, expected_revision: int) -> Session: ...

    async def show_dashboard(
        self, id: Id, dashboard_id: Id | None, expected_revision: int
    ) -> Session:
        """Put a dashboard in the panel beside the conversation, or clear the panel."""
        ...

    # Each of these appends to the session's record and publishes an event.

    async def add_message(self, session_id: Id, text: str, actor: Actor) -> SessionEntry: ...

    async def record_operator(
        self, session_id: Id, operator_id: OperatorId, note: str, actor: Actor
    ) -> SessionEntry: ...

    async def record_widget(
        self, session_id: Id, widget_id: Id, note: str, actor: Actor
    ) -> SessionEntry: ...
