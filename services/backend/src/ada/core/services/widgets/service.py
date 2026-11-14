from collections.abc import Sequence
from uuid import UUID, uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorId, OperatorKind
from ada.core.models.widgets import Widget, WidgetData
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService
from ada.core.services.schema.roles import check_widget

# Who starts the run when a widget asks for its data without naming one: nobody asked for
# it, the widget did, so it is the platform's doing.
WIDGET_ACTOR = Actor(kind=ActorKind.SYSTEM, name="widget")


class Widgets(WidgetService):
    def __init__(
        self,
        widgets: WidgetRepository,
        operators: OperatorRepository,
        sessions: SessionRepository,
        data_sources: DataSourceRepository,
        session_records: SessionService,
        runs: RunService,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.widgets = widgets
        self.operators = operators
        self.sessions = sessions
        self.data_sources = data_sources
        self.session_records = session_records
        self.runs = runs
        self.events = events
        self.clock = clock

    async def create(
        self,
        project_id: Id,
        operator_id: OperatorId,
        type: str,
        title: str,
        actor: Actor,
        spec: JsonObject | None = None,
        note: str = "",
        session_id: Id | None = None,
    ) -> Widget:
        if not type.strip():
            raise Invalid("A widget needs a type")
        operator = await self.operators.get(operator_id)
        if operator.project_id != project_id:
            raise Invalid("The operator belongs to another project")
        # What the widget needs (a measure, an x and a y, a geography role) must be
        # declared on its operator now, not discovered when someone first looks at it.
        check_widget(type.strip(), operator.output, spec or {})
        if session_id is not None:
            session = await self.sessions.get(session_id)
            if session.project_id != project_id:
                raise Invalid("The session belongs to another project")
        widget = Widget(
            id=uuid7(),
            project_id=project_id,
            session_id=session_id,
            operator_id=operator_id,
            type=type.strip(),
            title=title.strip(),
            spec=spec or {},
            note=note,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.widgets.add(widget)
        payload = {"widget_id": str(widget.id)}
        if session_id is not None:
            payload["session_id"] = str(session_id)
        await self.events.publish(
            Event(
                type=EventType.WIDGET_CREATED,
                project_id=project_id,
                payload=payload,
                at=self.clock.now(),
            )
        )
        if session_id is not None:
            await self.session_records.record_widget(session_id, widget.id, note, actor)
        return widget

    async def get(self, id: Id) -> Widget:
        return await self.widgets.get(id)

    async def list(self, project_id: Id) -> Sequence[Widget]:
        return await self.widgets.list(project_id)

    async def list_by_session(self, session_id: Id) -> Sequence[Widget]:
        await self.sessions.get(session_id)
        return await self.widgets.list_by_session(session_id)

    async def data(self, id: Id, run_id: Id | None = None, limit: int = 1000) -> WidgetData:
        widget = await self.widgets.get(id)
        if run_id is None:
            run = await self.runs.start(widget.project_id, WIDGET_ACTOR)
        else:
            run = await self.runs.get(run_id)
            if run.project_id != widget.project_id:
                raise Invalid("The run belongs to another project than the widget")
        rows = await self.runs.read(run.id, widget.operator_id, limit)
        operator = await self.operators.get(widget.operator_id)
        return WidgetData(
            widget_id=widget.id,
            run_id=run.id,
            output=operator.output,
            columns=rows.columns,
            rows=rows.rows,
            truncated=rows.truncated,
            is_scenario=run.is_scenario,
            is_stale=await self._is_stale(widget.operator_id),
        )

    async def _is_stale(self, operator_id: OperatorId) -> bool:
        """Whether a data source behind the operator failed its last refresh. Its widgets
        then show the last good snapshot, which a reader must not take for current data."""
        for operator in await self.operators.upstream(operator_id):
            if operator.kind is not OperatorKind.SOURCE:
                continue
            source = await self.data_sources.get(UUID(str(operator.params["data_source_id"])))
            if source.last_error is not None:
                return True
        return False
