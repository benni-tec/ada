import re
from collections.abc import Sequence
from uuid import UUID, uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.operators import OperatorId, OperatorKind
from ada.core.models.widgets import MAIN_INPUT, Widget, WidgetData
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

# Further inputs a widget may read besides its own operator, and how they are named.
MAX_INPUTS = 8
INPUT_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")


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
        inputs: dict[str, OperatorId] | None = None,
    ) -> Widget:
        if not type.strip():
            raise Invalid("A widget needs a type")
        operator = await self.operators.get(operator_id)
        if operator.project_id != project_id:
            raise Invalid("The operator belongs to another project")
        inputs = await self._inputs(project_id, inputs or {})
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
            inputs=inputs,
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

    async def update(
        self,
        id: Id,
        title: str | None = None,
        note: str | None = None,
        type: str | None = None,
        spec: JsonObject | None = None,
        inputs: dict[str, OperatorId] | None = None,
    ) -> Widget:
        widget = await self.widgets.get(id)
        changes: dict[str, object] = {}
        if inputs is not None:
            changes["inputs"] = await self._inputs(widget.project_id, inputs)
        if title is not None:
            if not title.strip():
                raise Invalid("A widget needs a title")
            changes["title"] = title.strip()
        if note is not None:
            changes["note"] = note
        if type is not None:
            if not type.strip():
                raise Invalid("A widget needs a type")
            changes["type"] = type.strip()
        if spec is not None:
            changes["spec"] = spec
        updated = widget.model_copy(update=changes)
        if updated.type != widget.type or updated.spec != widget.spec:
            operator = await self.operators.get(widget.operator_id)
            check_widget(updated.type, operator.output, updated.spec)
        await self.widgets.save(updated)
        payload = {"widget_id": str(updated.id)}
        if updated.session_id is not None:
            payload["session_id"] = str(updated.session_id)
        await self.events.publish(
            Event(
                type=EventType.WIDGET_UPDATED,
                project_id=updated.project_id,
                payload=payload,
                at=self.clock.now(),
            )
        )
        return updated

    async def get(self, id: Id) -> Widget:
        return await self.widgets.get(id)

    async def list(self, project_id: Id) -> Sequence[Widget]:
        return await self.widgets.list(project_id)

    async def list_by_session(self, session_id: Id) -> Sequence[Widget]:
        await self.sessions.get(session_id)
        return await self.widgets.list_by_session(session_id)

    async def data(
        self, id: Id, run_id: Id | None = None, limit: int = 1000, input: str = MAIN_INPUT
    ) -> WidgetData:
        widget = await self.widgets.get(id)
        operator_id = widget.all_inputs().get(input)
        if operator_id is None:
            names = ", ".join(widget.all_inputs())
            raise Invalid(f"Widget {widget.id} has no input {input!r}; it has {names}")
        if run_id is None:
            run = await self.runs.start(widget.project_id, WIDGET_ACTOR)
        else:
            run = await self.runs.get(run_id)
            if run.project_id != widget.project_id:
                raise Invalid("The run belongs to another project than the widget")
        rows = await self.runs.read(run.id, operator_id, limit)
        operator = await self.operators.get(operator_id)
        return WidgetData(
            widget_id=widget.id,
            run_id=run.id,
            input=input,
            output=operator.output,
            columns=rows.columns,
            rows=rows.rows,
            truncated=rows.truncated,
            is_scenario=run.is_scenario,
            is_stale=await self._is_stale(operator_id),
        )

    async def _inputs(self, project_id: Id, inputs: dict[str, OperatorId]) -> dict[str, OperatorId]:
        """Further inputs, checked: a name each (lowercase, digits and _, not "main"), at
        most MAX_INPUTS, every operator in the widget's project."""
        if len(inputs) > MAX_INPUTS:
            raise Invalid(f"A widget reads at most {MAX_INPUTS} further inputs")
        for name, operator_id in inputs.items():
            if name == MAIN_INPUT or not INPUT_NAME.fullmatch(name):
                raise Invalid(
                    f"Input name {name!r}: lowercase letters, digits and _, starting with a "
                    f"letter, and not {MAIN_INPUT!r} (the widget's own operator)"
                )
            try:
                operator = await self.operators.get(operator_id)
            except NotFound:
                raise Invalid(f"Input {name!r}: operator {operator_id} does not exist") from None
            if operator.project_id != project_id:
                raise Invalid(f"Input {name!r}: operator {operator_id} belongs to another project")
        return dict(inputs)

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
