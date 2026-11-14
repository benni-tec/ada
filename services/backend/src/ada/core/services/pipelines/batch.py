from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.errors import Conflict, Invalid, NotFound, Unavailable
from ada.core.models.operators import OperatorId
from ada.core.models.sessions import EntryKind
from ada.core.models.widgets import Widget
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.batches import (
    REFERENCE,
    Batch,
    BatchService,
    InputSlot,
    RegisterSource,
    Step,
    Transform,
    WidgetPart,
)
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService


@dataclass(frozen=True)
class _Made:
    """What a step made, as later steps may refer to it."""

    kind: str
    # The source id, operator id or widget id: what `refs` reports.
    id: str
    # For a registered source, its source operator, so "$s" works as an input too.
    operator_id: OperatorId | None = None


@dataclass
class _Run:
    """One batch as it goes: what each ref made, and what the session shows already."""

    project_id: Id
    actor: Actor
    session_id: Id | None
    made: dict[str, _Made] = field(default_factory=dict)
    shown: set[tuple[EntryKind, str]] = field(default_factory=set)
    widgets: list[Widget] = field(default_factory=list)


class Batches(BatchService):
    """Builds several steps in one call through the services the single tools use, so a
    step is checked, recorded and announced exactly as it would be on its own. All-or-
    nothing comes from the caller's unit of work: a failing step raises, and the call's
    transaction rolls back everything the steps before it wrote."""

    def __init__(
        self,
        projects: ProjectService,
        sources: SourceService,
        pipelines: PipelineService,
        widgets: WidgetService,
        sessions: SessionService,
        dispatcher: TaskDispatcher,
        after_commit: AfterCommit,
    ) -> None:
        self.projects = projects
        self.sources = sources
        self.pipelines = pipelines
        self.widgets = widgets
        self.sessions = sessions
        self.dispatcher = dispatcher
        self.after_commit = after_commit

    async def build(
        self, project_id: Id, steps: Sequence[Step], actor: Actor, session_id: Id | None = None
    ) -> Batch:
        await self.projects.get(project_id)
        if not steps:
            raise Invalid("A batch needs at least one step")
        run = _Run(project_id, actor, session_id)
        if session_id is not None:
            session = await self.sessions.get(session_id)
            if session.project_id != project_id:
                raise Invalid("The session belongs to another project")
            run.shown = {
                (entry.kind, entry.ref)
                for entry in await self.sessions.entries(session_id)
                if entry.ref is not None
            }
        for index, step in enumerate(steps):
            where = f"steps[{index}]" + (f" (ref {step.ref!r})" if step.ref else "")
            try:
                if step.ref is not None and step.ref in run.made:
                    raise Invalid(f"The ref {step.ref!r} is used by an earlier step")
                made = await self._step(run, step)
            except Unavailable as error:
                raise Unavailable(f"{where} failed: {error}") from error
            except (Invalid, NotFound, Conflict) as error:
                raise Invalid(f"{where} failed, so nothing was built: {error}") from error
            if step.ref is not None:
                run.made[step.ref] = made
        return Batch(
            refs={ref: made.id for ref, made in run.made.items()}, widgets=tuple(run.widgets)
        )

    async def _step(self, run: _Run, step: Step) -> _Made:
        if step.register_source is not None:
            return await self._register(run, step.register_source)
        if step.source_operator is not None:
            source_id = self._source(run, step.source_operator.data_source_id)
            operator = await self.pipelines.add_source(run.project_id, source_id, run.actor)
            await self._record(run, operator.id, step.note)
            return _Made("operator", operator.id)
        if step.input is not None:
            return await self._input(run, step.input, step.note)
        if step.transform is not None:
            return await self._transform(run, step.transform, step.note)
        assert step.widget is not None
        return await self._widget(run, step.widget, step.note)

    async def _register(self, run: _Run, part: RegisterSource) -> _Made:
        name, address = part.name.strip(), part.address.strip()
        existing = [
            source
            for source in await self.sources.list(run.project_id)
            if (source.name, source.address) == (name, address)
        ]
        if existing:
            source = existing[0]
        else:
            source = await self.sources.register(
                run.project_id,
                name,
                part.access_kind,
                address,
                part.format,
                options=part.options,
                freshness=part.freshness,
                declared_schema=part.declared_schema,
            )
        if part.refresh:
            source_id = source.id
            # After the commit: the worker must find the source this batch stored.
            self.after_commit.add(lambda: self.dispatcher.refresh_source(source_id))
        # Finds the source operator registration made.
        operator = await self.pipelines.add_source(run.project_id, source.id, run.actor)
        return _Made("source", str(source.id), operator_id=operator.id)

    async def _input(self, run: _Run, part: InputSlot, note: str) -> _Made:
        default = self._operator(run, part.default)
        operator = await self.pipelines.add_input(
            run.project_id, part.name, part.output, default, run.actor
        )
        await self._record(run, operator.id, note)
        return _Made("operator", operator.id)

    async def _transform(self, run: _Run, part: Transform, note: str) -> _Made:
        inputs = [self._operator(run, value) for value in part.inputs]
        operator = await self.pipelines.add_transform(
            run.project_id,
            part.sql,
            inputs,
            run.actor,
            roles=part.roles,
            materialize=part.materialize,
        )
        await self._record(run, operator.id, note)
        return _Made("operator", operator.id)

    async def _widget(self, run: _Run, part: WidgetPart, note: str) -> _Made:
        operator_id = self._operator(run, part.operator)
        wanted = (operator_id, part.type.strip(), part.title.strip(), part.spec or {})
        if run.session_id is not None:
            candidates = await self.widgets.list_by_session(run.session_id)
        else:
            candidates = [
                widget
                for widget in await self.widgets.list(run.project_id)
                if widget.session_id is None and widget.copied_from is None
            ]
        for widget in candidates:
            if (widget.operator_id, widget.type, widget.title, widget.spec) == wanted:
                break
        else:
            # With a session, the widget service records it there.
            widget = await self.widgets.create(
                run.project_id,
                operator_id,
                part.type,
                part.title,
                run.actor,
                spec=part.spec,
                note=note,
                session_id=run.session_id,
            )
        run.widgets.append(widget)
        return _Made("widget", str(widget.id))

    async def _record(self, run: _Run, operator_id: OperatorId, note: str) -> None:
        if run.session_id is None or (EntryKind.OPERATOR, operator_id) in run.shown:
            return
        await self.sessions.record_operator(run.session_id, operator_id, note, run.actor)
        run.shown.add((EntryKind.OPERATOR, operator_id))

    def _operator(self, run: _Run, value: str) -> OperatorId:
        """An operator id, or the operator an earlier step made or registered."""
        made = self._referenced(run, value)
        if made is None:
            return value
        if made.kind == "source":
            assert made.operator_id is not None
            return made.operator_id
        if made.kind != "operator":
            raise Invalid(f"{value} is a {made.kind}, not an operator")
        return made.id

    def _source(self, run: _Run, value: str) -> Id:
        made = self._referenced(run, value)
        if made is not None and made.kind != "source":
            raise Invalid(f"{value} is a {made.kind}, not a registered data source")
        try:
            return UUID(made.id if made else value)
        except ValueError:
            raise Invalid(f"{value!r} is not a data source id") from None

    def _referenced(self, run: _Run, value: str) -> _Made | None:
        if not value.startswith(REFERENCE):
            return None
        name = value.removeprefix(REFERENCE)
        if name not in run.made:
            raise Invalid(f"{value} names no earlier step; refer only to steps before this one")
        return run.made[name]
