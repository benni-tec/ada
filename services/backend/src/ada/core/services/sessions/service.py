from collections.abc import Sequence
from typing import Any
from uuid import uuid7

from ada.core.models.actors import PLATFORM, Actor
from ada.core.models.agents import FINISHED
from ada.core.models.attachments import AttachmentKind
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import (
    Context,
    DashboardContext,
    EntryKind,
    PipelineContext,
    Session,
    SessionAgent,
    SessionEntry,
    ToolCall,
    WidgetContext,
)
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    AgentTurnRepository,
    AttachmentRepository,
    DashboardRepository,
    OperatorRepository,
    ProjectRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.sessions import SessionService


class Sessions(SessionService):
    def __init__(
        self,
        sessions: SessionRepository,
        projects: ProjectRepository,
        dashboards: DashboardRepository,
        operators: OperatorRepository,
        widgets: WidgetRepository,
        attached: AttachmentRepository,
        attachments: AttachmentService,
        events: EventPublisher,
        clock: Clock,
        turns: AgentTurnRepository,
    ) -> None:
        self.sessions = sessions
        self.turns = turns
        self.projects = projects
        self.dashboards = dashboards
        self.operators = operators
        self.widgets = widgets
        self.attached = attached
        self.attachments = attachments
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
        await self._add(session)
        return session

    async def dashboard_agent_session(self, dashboard_id: Id) -> tuple[Session, bool]:
        dashboard = await self.dashboards.get(dashboard_id)
        showing = await self.attached.sessions_with(AttachmentKind.DASHBOARD, str(dashboard.id))
        panels = [
            session
            for session in await self.sessions.list(dashboard.project_id)
            if session.origin_dashboard_id == dashboard_id and session.id in showing
        ]
        if panels:
            # Ids are UUIDv7, so the largest is the newest even at equal timestamps.
            return max(panels, key=lambda session: (session.created_at, session.id)), False
        session = Session(
            id=uuid7(),
            project_id=dashboard.project_id,
            title=f"{dashboard.name} (agent)",
            origin_dashboard_id=dashboard_id,
            created_at=self.clock.now(),
        )
        await self._add(session)
        await self.attachments.attach(
            session.id, AttachmentKind.DASHBOARD, str(dashboard_id), PLATFORM
        )
        return session, True

    async def _add(self, session: Session) -> None:
        await self.sessions.add(session)
        # Announced, so a project page lists a session an agent started over MCP.
        await self.events.publish(
            Event(
                type=EventType.SESSION_CREATED,
                project_id=session.project_id,
                payload={"session_id": str(session.id)},
                at=self.clock.now(),
            )
        )

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

    async def delete(self, id: Id, actor: Actor) -> None:
        session = await self.sessions.get(id)
        if any(turn.status not in FINISHED for turn in await self.turns.list(id)):
            raise Invalid("The session's agent is still working: stop it or wait, then delete")
        # Other sessions stop showing it; each detach is announced to their pages.
        for other in await self.attached.sessions_with(AttachmentKind.SESSION, str(id)):
            if other == id:
                continue
            for attachment in await self.attached.list(other):
                if attachment.kind is AttachmentKind.SESSION and attachment.ref == str(id):
                    await self.attachments.detach(other, attachment.id, actor)
        await self.sessions.delete(id)
        await self.events.publish(
            Event(
                type=EventType.SESSION_DELETED,
                project_id=session.project_id,
                payload={"session_id": str(id)},
                at=self.clock.now(),
            )
        )

    async def add_message(
        self, session_id: Id, text: str, actor: Actor, context: Sequence[Context] = ()
    ) -> SessionEntry:
        if not text.strip():
            raise Invalid("A message needs text")
        session = await self.sessions.get(session_id)
        checked = tuple([await self._checked(session, item) for item in context])
        return await self._append(session, EntryKind.MESSAGE, text, None, actor, checked)

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

    async def record_agent_turn(self, session_id: Id, turn_id: Id, actor: Actor) -> SessionEntry:
        session = await self.sessions.get(session_id)
        return await self._append(session, EntryKind.AGENT_TURN, "", str(turn_id), actor)

    async def record_tool_call(self, session_id: Id, call: ToolCall, actor: Actor) -> SessionEntry:
        session = await self.sessions.get(session_id)
        error = _cut(call.error, MAX_ERROR) if call.error is not None else None
        kept = call.model_copy(update={"arguments": shortened(call.arguments), "error": error})
        return await self._append(session, EntryKind.TOOL_CALL, "", None, actor, tool_call=kept)

    async def check(self, session_id: Id, project_id: Id | None = None) -> Session:
        session = await self.sessions.get(session_id)
        if project_id is not None and session.project_id != project_id:
            raise Invalid("The session belongs to another project than the one given")
        return session

    async def create_child(
        self, parent_session_id: Id, title: str, agent: SessionAgent, actor: Actor
    ) -> Session:
        parent = await self.sessions.get(parent_session_id)
        if agent is SessionAgent.SESSION:
            raise Invalid("A delegated session is a research or an analysis session")
        if parent.agent is not SessionAgent.SESSION:
            raise Invalid("A delegated session cannot delegate further")
        child = Session(
            id=uuid7(),
            project_id=parent.project_id,
            title=_title(title),
            agent=agent,
            parent_session_id=parent.id,
            created_at=self.clock.now(),
        )
        await self._add(child)
        await self._append(parent, EntryKind.DELEGATION, child.title, str(child.id), actor)
        return child

    async def record_report(self, child_session_id: Id, text: str, actor: Actor) -> SessionEntry:
        child = await self.sessions.get(child_session_id)
        if child.agent is SessionAgent.SESSION or child.parent_session_id is None:
            raise Invalid("Only a delegated session reports back, into the session it serves")
        if not text.strip():
            raise Invalid("A report needs text")
        parent = await self.sessions.get(child.parent_session_id)
        return await self._append(parent, EntryKind.REPORT, text, str(child.id), actor)

    async def record_alert(self, session_id: Id, alert_id: Id, text: str) -> SessionEntry:
        session = await self.sessions.get(session_id)
        return await self._append(session, EntryKind.ALERT, text, str(alert_id), PLATFORM)

    async def _checked(self, session: Session, item: Context) -> Context:
        """A context item that names something of the session's project. A message about
        another project's pipeline would send the agent building on it."""
        match item:
            case PipelineContext():
                operator = await self.operators.get(item.operator_id)
                if operator.project_id != session.project_id:
                    raise Invalid("The pipeline belongs to another project than the session")
                return item
            case DashboardContext():
                await self._check_dashboard(item.dashboard_id, session.project_id)
                slot = item.slot.strip() if item.slot is not None else None
                return item.model_copy(update={"slot": slot or None})
            case WidgetContext():
                widget = await self.widgets.get(item.widget_id)
                if widget.project_id != session.project_id:
                    raise Invalid("The widget belongs to another project than the session")
                return item

    async def _append(
        self,
        session: Session,
        kind: EntryKind,
        text: str,
        ref: str | None,
        actor: Actor,
        context: tuple[Context, ...] = (),
        tool_call: ToolCall | None = None,
    ) -> SessionEntry:
        entry = SessionEntry(
            id=uuid7(),
            session_id=session.id,
            kind=kind,
            text=text,
            ref=ref,
            actor=actor,
            created_at=self.clock.now(),
            context=context,
            tool_call=tool_call,
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


# How much of a tool call's arguments the record keeps: enough to see what was asked, not
# whole datasets or documents. SQL is what a person reads to follow the work, so it is kept
# whole up to a much greater length.
MAX_TEXT = 200
MAX_SQL = 2000
MAX_ITEMS = 10
MAX_ERROR = 2000
SQL_KEYS = frozenset({"sql", "select", "where", "group_by", "having", "order_by"})


def shortened(value: Any, key: str | None = None) -> Any:
    """`value` with strings over 200 characters cut (SQL, under the keys in SQL_KEYS, over
    2,000) and lists over 10 items cut, at any depth. A cut string ends with "…"; a cut
    list ends with a string saying how many items were left out."""
    match value:
        case str():
            return _cut(value, MAX_SQL if key in SQL_KEYS else MAX_TEXT)
        case dict():
            return {k: shortened(v, k) for k, v in value.items()}
        case list() | tuple():
            kept = [shortened(item, key) for item in value[:MAX_ITEMS]]
            if len(value) > MAX_ITEMS:
                kept.append(f"… {len(value) - MAX_ITEMS} more")
            return kept
        case _:
            return value


def _cut(text: str, length: int) -> str:
    return text if len(text) <= length else text[:length] + "…"


def _title(title: str) -> str:
    title = title.strip()
    if not title:
        raise Invalid("A session needs a title")
    return title
