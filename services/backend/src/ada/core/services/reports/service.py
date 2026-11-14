from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.reports import Report, ReportVersion, Template, TemplateKind, VersionBump
from ada.core.models.runs import Run
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    ProjectRepository,
    ReportRepository,
    SessionRepository,
    SnapshotRepository,
    TemplateRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.reports import ReportService
from ada.core.services.ports.runs import RunService
from ada.core.services.reports import content as tree
from ada.core.services.reports.sources import SourcesList
from ada.core.services.reports.versions import FIRST, State, decide, parse_version, required

# The content that fills a template instead of spelling out a tree: {"slots": {name: id}}.
FILL_KEY = "slots"


class Reports(ReportService):
    """Reports and their versions.

    A version is frozen at one run: before it is stored, the run executes every widget's
    operator, so the run fixes the snapshot each source is read from and the version shows
    the same numbers for as long as it exists. The sources list is worked out from that
    run and stored with the version.
    """

    def __init__(
        self,
        reports: ReportRepository,
        templates: TemplateRepository,
        projects: ProjectRepository,
        sessions: SessionRepository,
        widgets: WidgetRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        data_sources: DataSourceRepository,
        dashboards: DashboardService,
        runs: RunService,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.reports = reports
        self.templates = templates
        self.projects = projects
        self.sessions = sessions
        self.widgets = widgets
        self.dashboards = dashboards
        self.runs = runs
        self.events = events
        self.clock = clock
        self.sources = SourcesList(operators, snapshots, data_sources)

    async def get(self, id: Id) -> Report:
        return await self.reports.get(id)

    async def list(self, project_id: Id) -> Sequence[Report]:
        await self.projects.get(project_id)
        return await self.reports.list(project_id)

    async def version(self, version_id: Id) -> ReportVersion:
        return await self.reports.get_version(version_id)

    async def versions(self, id: Id) -> Sequence[ReportVersion]:
        await self.reports.get(id)
        versions = await self.reports.versions(id)
        return sorted(versions, key=lambda version: parse_version(version.version))

    async def create(
        self,
        project_id: Id,
        name: str,
        content: JsonObject,
        run_id: Id,
        time_range: TimeRange,
        actor: Actor,
        session_id: Id | None = None,
        dashboard_id: Id | None = None,
        template_id: Id | None = None,
    ) -> ReportVersion:
        await self.projects.get(project_id)
        template = await self._template(template_id, project_id)
        blocks = await self._blocks(project_id, content, template)
        run = await self._pinned(project_id, run_id)
        return await self._create(
            project_id,
            name,
            blocks,
            run,
            _checked_range(run, time_range),
            actor,
            session_id,
            dashboard_id,
            template_id,
            None,
        )

    async def add_version(
        self,
        id: Id,
        content: JsonObject,
        run_id: Id,
        time_range: TimeRange,
        actor: Actor,
        bump: VersionBump | None = None,
    ) -> ReportVersion:
        report = await self.reports.get(id)
        latest = await self._latest(report)
        # A version keeps the template of the report; a fill fills that template again.
        template = await self._template(latest.template_id, report.project_id)
        blocks = await self._blocks(report.project_id, content, template)
        run = await self._pinned(report.project_id, run_id)
        return await self._next(
            report,
            latest,
            blocks,
            run,
            _checked_range(run, time_range),
            actor,
            bump,
            latest.template_id,
            None,
        )

    async def generate_from_dashboard(
        self,
        dashboard_id: Id,
        name: str,
        actor: Actor,
        run_id: Id | None = None,
        time_range: TimeRange | None = None,
    ) -> ReportVersion:
        dashboard = await self.dashboards.get(dashboard_id)
        current = await self.dashboards.current(dashboard_id)
        blocks = _dashboard_blocks(current.slots) if current is not None else ()
        if current is None or not blocks:
            raise Invalid(
                f"Dashboard {dashboard_id} shows no widgets, so there is nothing to report"
            )
        await self._check_widgets(dashboard.project_id, blocks)
        if run_id is None:
            # A dashboard shows one run at a time; a report freezes one, started for the
            # range asked for, or else the range the dashboard shows by default.
            range_ = time_range if time_range is not None else dashboard.default_time_range
            run = await self.runs.start(dashboard.project_id, actor, range_)
        else:
            run = await self._pinned(dashboard.project_id, run_id)
            range_ = _checked_range(run, time_range if time_range is not None else run.time_range)
        existing = await self._named(dashboard.project_id, _name(name), dashboard_id=dashboard_id)
        if existing is not None:
            latest = await self._latest(existing)
            return await self._next(
                existing, latest, blocks, run, range_, actor, None, None, current.id
            )
        return await self._create(
            dashboard.project_id,
            name,
            blocks,
            run,
            range_,
            actor,
            None,
            dashboard_id,
            None,
            current.id,
        )

    # Making versions

    async def _create(
        self,
        project_id: Id,
        name: str,
        blocks: tuple[tree.Block, ...],
        run: Run,
        time_range: TimeRange,
        actor: Actor,
        session_id: Id | None,
        dashboard_id: Id | None,
        template_id: Id | None,
        dashboard_version_id: Id | None,
    ) -> ReportVersion:
        name = _name(name)
        await self._check_owner(project_id, session_id, dashboard_id)
        if await self._named(project_id, name, session_id, dashboard_id) is not None:
            raise Invalid(f"There is a report named {name!r} already; add a version to it instead")
        version_id = uuid7()
        report = Report(
            id=uuid7(),
            project_id=project_id,
            name=name,
            session_id=session_id,
            dashboard_id=dashboard_id,
            # Points at the first version from the start, so a new report is at revision 1.
            latest_version_id=version_id,
            created_at=self.clock.now(),
        )
        await self.reports.add(report)
        return await self._freeze(
            report,
            version_id,
            FIRST,
            blocks,
            run,
            time_range,
            actor,
            template_id,
            dashboard_version_id,
        )

    async def _next(
        self,
        report: Report,
        latest: ReportVersion,
        blocks: tuple[tree.Block, ...],
        run: Run,
        time_range: TimeRange,
        actor: Actor,
        bump: VersionBump | None,
        template_id: Id | None,
        dashboard_version_id: Id | None,
    ) -> ReportVersion:
        previous = State(
            operators=await self._operators(tree.stored_blocks(latest.content)),
            run_id=latest.run_id,
            time_range=latest.time_range,
            blocks=latest.content.get(tree.BLOCKS_KEY, []),
        )
        following = State(
            operators=await self._operators(blocks),
            run_id=run.id,
            time_range=time_range,
            blocks=tree.dump(blocks),
        )
        need = required(previous, following)
        if need is None:
            raise Invalid(
                f"Nothing changed against version {latest.version}: same widgets, run, time "
                "range and text"
            )
        number = decide(latest.version, need, bump)
        version_id = uuid7()
        # Moving the pointer is the write that two concurrent versions conflict on.
        report = await self.reports.update(
            report.model_copy(update={"latest_version_id": version_id}), report.revision
        )
        return await self._freeze(
            report,
            version_id,
            number,
            blocks,
            run,
            time_range,
            actor,
            template_id,
            dashboard_version_id,
        )

    async def _freeze(
        self,
        report: Report,
        version_id: Id,
        number: str,
        blocks: tuple[tree.Block, ...],
        run: Run,
        time_range: TimeRange,
        actor: Actor,
        template_id: Id | None,
        dashboard_version_id: Id | None,
    ) -> ReportVersion:
        widgets = [await self.widgets.get(id) for id in tree.widget_ids(blocks)]
        for operator_id in dict.fromkeys(widget.operator_id for widget in widgets):
            # Fixes the snapshots the widget reads; a run reused by a later version
            # keeps what it fixed first.
            run = await self.runs.execute(run.id, operator_id)
        version = ReportVersion(
            id=version_id,
            report_id=report.id,
            version=number,
            run_id=run.id,
            time_range=time_range,
            content={
                tree.BLOCKS_KEY: tree.dump(blocks),
                tree.SOURCES_KEY: await self.sources.build(run, widgets),
            },
            template_id=template_id,
            dashboard_version_id=dashboard_version_id,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.reports.add_version(version)
        await self.events.publish(
            Event(
                type=EventType.REPORT_VERSION_CREATED,
                project_id=report.project_id,
                payload={
                    "report_id": str(report.id),
                    "version_id": str(version.id),
                    "version": version.version,
                },
                at=self.clock.now(),
            )
        )
        return version

    # Checks

    async def _blocks(
        self, project_id: Id, content: JsonObject, template: Template | None
    ) -> tuple[tree.Block, ...]:
        if isinstance(content, dict) and set(content) == {FILL_KEY}:
            if template is None:
                raise Invalid("`slots` fills a template; name the template, or write `blocks`")
            blocks = _fill(template, content[FILL_KEY])
        else:
            blocks = tree.parse(content, tree.Tree.REPORT)
        if not blocks:
            raise Invalid("A report needs at least one block")
        await self._check_widgets(project_id, blocks)
        return blocks

    async def _check_widgets(self, project_id: Id, blocks: Sequence[tree.Block]) -> None:
        for widget_id in tree.widget_ids(blocks):
            widget = await self._widget(widget_id)
            if widget.project_id != project_id:
                raise Invalid(f"Widget {widget_id} belongs to another project than the report")

    async def _widget(self, widget_id: Id) -> Widget:
        try:
            return await self.widgets.get(widget_id)
        except NotFound:
            raise Invalid(f"The content shows widget {widget_id}, which does not exist") from None

    async def _operators(self, blocks: Sequence[tree.Block]) -> frozenset[str]:
        return frozenset([(await self._widget(id)).operator_id for id in tree.widget_ids(blocks)])

    async def _template(self, template_id: Id | None, project_id: Id) -> Template | None:
        if template_id is None:
            return None
        template = await self.templates.get(template_id)
        if template.project_id != project_id:
            raise Invalid(f"Template {template_id} belongs to another project")
        if template.kind is not TemplateKind.REPORT:
            raise Invalid(f"Template {template_id} is a {template.kind.value} template")
        return template

    async def _pinned(self, project_id: Id, run_id: Id) -> Run:
        run = await self.runs.get(run_id)
        if run.project_id != project_id:
            raise Invalid(f"Run {run_id} belongs to another project than the report")
        return run

    async def _check_owner(
        self, project_id: Id, session_id: Id | None, dashboard_id: Id | None
    ) -> None:
        if (session_id is None) == (dashboard_id is None):
            raise Invalid("A report belongs to exactly one session or one dashboard; name one")
        if session_id is not None:
            session = await self.sessions.get(session_id)
            if session.project_id != project_id:
                raise Invalid("The session belongs to another project than the report")
        if dashboard_id is not None:
            dashboard = await self.dashboards.get(dashboard_id)
            if dashboard.project_id != project_id:
                raise Invalid("The dashboard belongs to another project than the report")

    async def _named(
        self,
        project_id: Id,
        name: str,
        session_id: Id | None = None,
        dashboard_id: Id | None = None,
    ) -> Report | None:
        """The owner's report of this name, if there is one."""
        for report in await self.reports.list(project_id):
            if (
                report.name == name
                and report.session_id == session_id
                and report.dashboard_id == dashboard_id
            ):
                return report
        return None

    async def _latest(self, report: Report) -> ReportVersion:
        if report.latest_version_id is None:
            raise Invalid(f"Report {report.id} has no version yet")
        return await self.reports.get_version(report.latest_version_id)


def _name(name: str) -> str:
    name = name.strip()
    if not name:
        raise Invalid("A report needs a name")
    return name


def _checked_range(run: Run, time_range: TimeRange) -> TimeRange:
    """A version records its run's time range: the data period and the as-of time are
    pinned together, so they cannot disagree."""
    if time_range != run.time_range:
        raise Invalid(
            f"Run {run.id} was started for {_describe(run.time_range)}, not "
            f"{_describe(time_range)}; start a run for that range, or leave the range out"
        )
    return time_range


def _describe(time_range: TimeRange) -> str:
    start = time_range.start.isoformat() if time_range.start else "the beginning"
    end = time_range.end.isoformat() if time_range.end else "now"
    return f"{start} to {end}"


def _fill(template: Template, given: Any) -> tuple[tree.Block, ...]:
    """The template's tree with its slots filled: by the widgets given, else by a slot's
    default widget. Every slot must end up with one."""
    if not isinstance(given, dict):
        raise Invalid("`slots` maps each slot name of the template to a widget id")
    names = {slot.name for slot in template.slots}
    unknown = sorted(set(given) - names)
    if unknown:
        raise Invalid(f"Template {template.id} has no slots {unknown}; it has {sorted(names)}")
    widgets: dict[str, Id] = {}
    missing = []
    for slot in template.slots:
        value = given.get(slot.name, slot.widget_id)
        if value is None:
            missing.append(slot.name)
            continue
        try:
            widgets[slot.name] = value if isinstance(value, UUID) else UUID(str(value))
        except ValueError:
            raise Invalid(f"Slot {slot.name!r}: {value!r} is not a widget id") from None
    if missing:
        raise Invalid(f"Fill every slot of the template; missing: {missing}")
    return tree.fill(tree.stored_blocks(template.content), widgets)


def _dashboard_blocks(slots: Sequence[Slot]) -> tuple[tree.Block, ...]:
    """A dashboard's widgets as a report reads them: top to bottom, then left to right on
    its grid. Empty slots are left out."""

    def place(slot: Slot) -> tuple[int, int]:
        return _coordinate(slot.layout.get("y")), _coordinate(slot.layout.get("x"))

    filled = sorted((slot for slot in slots if slot.widget_id is not None), key=place)
    return tuple(tree.WidgetBlock(type="widget", widget_id=slot.widget_id) for slot in filled)


def _coordinate(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
