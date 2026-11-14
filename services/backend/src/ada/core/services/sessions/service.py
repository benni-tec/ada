from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import EntryKind, Session, SessionEntry
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DashboardRepository,
    OperatorRepository,
    ProjectRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.sessions import SessionService


class Sessions(SessionService):
    def __init__(
        self,
        sessions: SessionRepository,
        projects: ProjectRepository,
        dashboards: DashboardRepository,
        operators: OperatorRepository,
        widgets: WidgetRepository,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.projects = projects
        self.dashboards = dashboards
        self.operators = operators
        self.widgets = widgets
        self.events = events
        self.clock = clock

    async def create(
        self, project_id: Id, title: str, origin_dashboard_id: Id | None = None
    ) -> Session:
        await self.projects.get(project_id)
        if origin_dashboard_id is not None:
            await self._check_dashboard(origin_dashboard_id, project_id)
        session = Session(
            id=uuid7(),
            project_id=project_id,
            title=_title(title),
            origin_dashboard_id=origin_dashboard_id,
            created_at=self.clock.now(),
        )
        await self.sessions.add(session)
        return session

    async def get(self, id: Id) -> Session:
        return await self.sessions.get(id)

    async def list(self, project_id: Id) -> Sequence[Session]:
        return await self.sessions.list(project_id)

    async def entries(self, session_id: Id) -> Sequence[SessionEntry]:
        # Read the session first, so an unknown id is a 404 and not an empty record.
        await self.sessions.get(session_id)
        return await self.sessions.entries(session_id)

    async def rename(self, id: Id, title: str, expected_revision: int) -> Session:
        session = await self.sessions.get(id)
        return await self.sessions.update(
            session.model_copy(update={"title": _title(title)}), expected_revision
        )

    async def show_dashboard(
        self, id: Id, dashboard_id: Id | None, expected_revision: int
    ) -> Session:
        session = await self.sessions.get(id)
        if dashboard_id is not None:
            await self._check_dashboard(dashboard_id, session.project_id)
        return await self.sessions.update(
            session.model_copy(update={"panel_dashboard_id": dashboard_id}), expected_revision
        )

    async def add_message(self, session_id: Id, text: str, actor: Actor) -> SessionEntry:
        if not text.strip():
            raise Invalid("A message needs text")
        session = await self.sessions.get(session_id)
        return await self._append(session, EntryKind.MESSAGE, text, None, actor)

    async def record_operator(
        self, session_id: Id, operator_id: OperatorId, note: str, actor: Actor
    ) -> SessionEntry:
        session = await self.sessions.get(session_id)
        operator = await self.operators.get(operator_id)
        if operator.project_id != session.project_id:
            raise Invalid("The operator belongs to another project than the session")
        return await self._append(session, EntryKind.OPERATOR, note, operator_id, actor)

    async def record_widget(
        self, session_id: Id, widget_id: Id, note: str, actor: Actor
    ) -> SessionEntry:
        session = await self.sessions.get(session_id)
        widget = await self.widgets.get(widget_id)
        if widget.project_id != session.project_id:
            raise Invalid("The widget belongs to another project than the session")
        return await self._append(session, EntryKind.WIDGET, note, str(widget_id), actor)

    async def _append(
        self, session: Session, kind: EntryKind, text: str, ref: str | None, actor: Actor
    ) -> SessionEntry:
        entry = SessionEntry(
            id=uuid7(),
            session_id=session.id,
            kind=kind,
            text=text,
            ref=ref,
            actor=actor,
            created_at=self.clock.now(),
        )
        await self.sessions.add_entry(entry)
        await self.events.publish(
            Event(
                type=EventType.SESSION_ENTRY_ADDED,
                project_id=session.project_id,
                payload={"session_id": str(session.id), "entry_id": str(entry.id)},
                at=self.clock.now(),
            )
        )
        return entry

    async def _check_dashboard(self, dashboard_id: Id, project_id: Id) -> None:
        dashboard = await self.dashboards.get(dashboard_id)
        if dashboard.project_id != project_id:
            raise Invalid("The dashboard belongs to another project than the session")


def _title(title: str) -> str:
    title = title.strip()
    if not title:
        raise Invalid("A session needs a title")
    return title
