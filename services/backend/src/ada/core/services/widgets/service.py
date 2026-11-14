import re
from collections.abc import Sequence
from uuid import UUID, uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import Invalid, NotFound, Unavailable
from ada.core.models.events import Event, EventType
from ada.core.models.judges import JudgeContext, JudgeInput, JudgeKind
from ada.core.models.operators import OperatorId, OperatorKind
from ada.core.models.schema import Schema
from ada.core.models.widgets import MAIN_INPUT, Widget, WidgetData
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.judges import JudgeService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService
from ada.core.services.schema.roles import check_widget
from ada.core.services.widgets.specs import CUSTOM, custom_problems

# Who starts the run when a widget asks for its data without naming one: nobody asked for
# it, the widget did, so it is the platform's doing.
WIDGET_ACTOR = Actor(kind=ActorKind.SYSTEM, name="widget")

# Further inputs a widget may read besides its own operator, and how they are named.
MAX_INPUTS = 8
INPUT_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")

# The rows of each input the judge sees beside a custom widget's code.
JUDGE_SAMPLE_ROWS = 20
# What a widget's frame reports is kept up to this length.
MAX_RENDER_ERROR = 2_000


class Widgets(WidgetService):
    def __init__(
        self,
        widgets: WidgetRepository,
        operators: OperatorRepository,
        sessions: SessionRepository,
        data_sources: DataSourceRepository,
        session_records: SessionService,
        runs: RunService,
        judges: JudgeService,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.widgets = widgets
        self.operators = operators
        self.sessions = sessions
        self.data_sources = data_sources
        self.session_records = session_records
        self.runs = runs
        self.judges = judges
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
        _check(type.strip(), operator.output, spec or {})
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
        widget = await self._reviewed(widget)
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
            _check(updated.type, operator.output, updated.spec)
        if _drawing(updated) != _drawing(widget):
            # It draws differently now: the last drawing's error is about something gone.
            updated = await self._reviewed(updated.model_copy(update={"render_error": None}))
        await self.widgets.save(updated)
        await self._announce(updated)
        return updated

    async def report_render(self, id: Id, error: str | None) -> None:
        widget = await self.widgets.get(id)
        if error is not None:
            error = error[:MAX_RENDER_ERROR]
        if error == widget.render_error:
            return
        await self.widgets.set_render_error(id, error)
        # Frames draw what they drew; only the cards' error lines need the news.
        await self._announce(widget, render_only=True)

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

    async def _reviewed(self, widget: Widget) -> Widget:
        """The widget with its judge's verdict: a custom widget's code is reviewed with a
        sample of every input, all read in one run; the other types are never reviewed. A
        blocking verdict refuses the widget."""
        if widget.type != CUSTOM:
            return widget.model_copy(update={"verdict": None})
        code, css = widget.spec.get("code") or "", widget.spec.get("css") or ""
        verdict = await self.judges.review(
            widget.project_id,
            JudgeKind.WIDGET_CODE,
            content=f"{code}\n/* css */\n{css}",
            context=JudgeContext(
                inputs=await self._samples(widget), note=f"custom widget: {widget.title}"
            ),
        )
        if verdict.blocking:
            findings = "; ".join(
                f"{finding.message} (in `{finding.excerpt.strip()}`)"
                for finding in verdict.findings
            )
            raise Invalid(
                "The judge refused this custom widget's code: "
                + (findings or verdict.reason or "it gave no findings")
            )
        return widget.model_copy(update={"verdict": verdict})

    async def _samples(self, widget: Widget) -> tuple[JudgeInput, ...]:
        """The first rows of every input in one new run. An input that cannot be read now
        gives its columns only."""
        run = await self.runs.start(widget.project_id, WIDGET_ACTOR)
        samples: list[JudgeInput] = []
        for name, operator_id in widget.all_inputs().items():
            try:
                rows = await self.runs.read(run.id, operator_id, JUDGE_SAMPLE_ROWS)
            except Invalid, NotFound, Unavailable:
                operator = await self.operators.get(operator_id)
                samples.append(JudgeInput(name=name, columns=operator.output.columns))
            else:
                samples.append(JudgeInput(name=name, columns=rows.columns, rows=rows.rows))
        return tuple(samples)

    async def _announce(self, widget: Widget, render_only: bool = False) -> None:
        payload: dict[str, object] = {"widget_id": str(widget.id)}
        if widget.session_id is not None:
            payload["session_id"] = str(widget.session_id)
        if render_only:
            payload["render_only"] = True
        await self.events.publish(
            Event(
                type=EventType.WIDGET_UPDATED,
                project_id=widget.project_id,
                payload=payload,
                at=self.clock.now(),
            )
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


def _check(type: str, output: Schema, spec: JsonObject) -> None:
    """Whether a widget of this type can show the output with this spec. A custom widget
    draws whatever its code draws, so only its spec is checked."""
    if type != CUSTOM:
        check_widget(type, output, spec)
        return
    problems = custom_problems(spec)
    if problems:
        raise Invalid("A custom widget cannot be made from this spec: " + "; ".join(problems))


def _drawing(widget: Widget) -> tuple[object, ...]:
    """What decides how a widget draws: its type, spec and inputs."""
    return widget.type, widget.spec, widget.inputs
