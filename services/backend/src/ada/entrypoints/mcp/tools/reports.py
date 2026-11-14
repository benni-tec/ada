from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.reports import Report, ReportVersion, Template, TemplateKind, VersionBump
from ada.core.models.runs import Run
from ada.core.models.time import TimeRange
from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.ports.runs import RunService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject

CONTENT_FORMAT = """
The content is a JSON component tree, `{"blocks": [...]}`. Blocks, by `type`:

- {"type": "heading", "text": "...", "level": 1|2|3}   (level defaults to 2)
- {"type": "text", "text": "..."}   plain text; a blank line starts a paragraph
- {"type": "callout", "tone": "note"|"finding"|"warning", "title": "...", "text": "..."}
- {"type": "widget", "widget_id": "<id>", "caption": "..."}   caption optional
- {"type": "section", "title": "...", "blocks": [...]}   nests up to 4 deep

Only widget blocks show data, and only by widget id: make the widget first with
create_widget, then place it. Static blocks take exactly the fields above; anything else
(rows, values, ids) is rejected, so do not write numbers from the data into text, show a
widget instead. Leave out `sources`: the platform generates the sources list from the
widgets' pipelines.
""".strip()


class ReportView(DomainModel):
    report: Report
    # The version shown, with its content tree and its generated `sources` list.
    version: ReportVersion
    # Every version number of the report, lowest first.
    versions: tuple[str, ...]
    # Where a person reads this version in the frontend, relative to the host.
    url: str


class ReportListing(DomainModel):
    report: Report
    url: str


def report_url(report: Report, version: ReportVersion | None = None) -> str:
    url = f"/projects/{report.project_id}/reports/{report.id}"
    return f"{url}?version={version.version}" if version is not None else url


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool(
        description=f"""Write a report: a document frozen at one run, so it always shows
the same numbers, with every number traceable to its pipeline. Creates the report with
version 1.0.0. It belongs to exactly one owner: pass `session_id` for a report written in
a session, or `dashboard_id` for one about a dashboard (generate_report_from_dashboard
does that for you).

`run_id` pins the run whose data the widgets show, e.g. the run of preview_operator;
without one a new run is started for `time_range` (default: open). The version records the
run's time range.

{CONTENT_FORMAT}

To fill a report template instead, pass `template_id` and as content
`{{"slots": {{"<slot name>": "<widget id>", ...}}}}`; slots with a default widget may be left
out. Returns the report, the version with its sources list, and the `url` to give the
person."""
    )
    @inject
    async def create_report(
        project_id: Id,
        name: str,
        content: JsonObject,
        reports: FromDishka[ReportService],
        runs: FromDishka[RunService],
        run_id: Id | None = None,
        time_range: TimeRange | None = None,
        session_id: Id | None = None,
        dashboard_id: Id | None = None,
        template_id: Id | None = None,
    ) -> ReportView:
        actor = calling_agent()
        run = await _run(runs, project_id, run_id, time_range, actor)
        version = await reports.create(
            project_id,
            name,
            content,
            run.id,
            time_range if time_range is not None else run.time_range,
            actor,
            session_id=session_id,
            dashboard_id=dashboard_id,
            template_id=template_id,
        )
        return await _view(reports, version)

    @mcp.tool(
        description=f"""Add the next version of a report. Versions are immutable, so this
is how a report changes. The version number follows from what changed against the latest
version: major when the widgets' pipelines changed (numbers not comparable), minor for the
same report on another run or time range (e.g. new data), patch when only text or layout
changed. Pass `bump` ("major", "minor" or "patch") to choose a higher level; a lower one
than the change needs is rejected, and so is a version that changes nothing.

Without `run_id` a new run is started for `time_range`, which gives the latest data. Pass
`expected_revision` (the report's `revision` when you read it) to fail instead of adding
on top of a version someone else added meanwhile.

{CONTENT_FORMAT}

A report made from a template may again be given `{{"slots": {{...}}}}` as content. Start
from get_report's content, change it, and leave out `sources`. Returns the report, the new
version and its `url`."""
    )
    @inject
    async def add_report_version(
        report_id: Id,
        content: JsonObject,
        reports: FromDishka[ReportService],
        runs: FromDishka[RunService],
        run_id: Id | None = None,
        time_range: TimeRange | None = None,
        bump: VersionBump | None = None,
        expected_revision: int | None = None,
    ) -> ReportView:
        actor = calling_agent()
        report = await reports.get(report_id)
        if expected_revision is not None and report.revision != expected_revision:
            raise Conflict("report", report_id, expected_revision, report.revision)
        run = await _run(runs, report.project_id, run_id, time_range, actor)
        version = await reports.add_version(
            report_id,
            content,
            run.id,
            time_range if time_range is not None else run.time_range,
            actor,
            bump=bump,
        )
        return await _view(reports, version)

    @mcp.tool
    @inject
    async def generate_report_from_dashboard(
        dashboard_id: Id,
        name: str,
        reports: FromDishka[ReportService],
        run_id: Id | None = None,
        time_range: TimeRange | None = None,
    ) -> ReportView:
        """Freeze a dashboard into a report: its current widgets, top to bottom, at one
        run and time range, with the dashboard version recorded. Without `run_id` a run is
        started for `time_range`, or else for the dashboard's default range. When the
        dashboard already has a report of this `name`, this adds its next version (minor
        for new data, major when the dashboard's widgets changed) instead of a second
        report. Add text around the widgets afterwards with add_report_version. Returns
        the report, the version and its `url`."""
        version = await reports.generate_from_dashboard(
            dashboard_id, name, calling_agent(), run_id=run_id, time_range=time_range
        )
        return await _view(reports, version)

    @mcp.tool
    @inject
    async def list_reports(
        project_id: Id,
        reports: FromDishka[ReportService],
        session_id: Id | None = None,
        dashboard_id: Id | None = None,
    ) -> Sequence[ReportListing]:
        """List a project's reports, oldest first, each with its url; pass `session_id`
        or `dashboard_id` for only the reports that session or dashboard produced. Use it
        before writing a report, to add a version to an existing one instead."""
        return [
            ReportListing(report=report, url=report_url(report))
            for report in await reports.list(project_id)
            if (session_id is None or report.session_id == session_id)
            and (dashboard_id is None or report.dashboard_id == dashboard_id)
        ]

    @mcp.tool
    @inject
    async def get_report(
        report_id: Id, reports: FromDishka[ReportService], version: str | None = None
    ) -> ReportView:
        """Read a report version: its content tree, its run and time range, and the
        generated `sources` list (each data source behind its widgets, with the address
        and the fetch time of the data the run used). `version` is a number like "1.2.0";
        without it the latest version is returned. Returns the report, the version, every
        version number, and the `url`."""
        report = await reports.get(report_id)
        versions = await reports.versions(report_id)
        if version is None:
            chosen = next(v for v in versions if v.id == report.latest_version_id)
        else:
            found = [v for v in versions if v.version == version]
            if not found:
                raise NotFound("report version", f"{version} of report {report_id}")
            chosen = found[0]
        return _shown(report, chosen, versions)

    @mcp.tool
    @inject
    async def create_template(
        project_id: Id,
        name: str,
        kind: TemplateKind,
        slots: Sequence[Slot],
        templates: FromDishka[TemplateService],
        content: JsonObject | None = None,
    ) -> Template:
        """Create a template with named slots. A "report" template is a component tree
        whose widget blocks name a slot instead of a widget, e.g.
        {"blocks": [{"type": "heading", "text": "Headline gap"},
        {"type": "widget", "slot": "gap"}]}; the blocks are those of create_report. Without
        `content` the slots in their order make the tree. A "dashboard" template has no
        tree: its slots carry a `layout` of {x, y, w, h} on a 12-column grid.

        Each slot has a `name`, a `description` of the widget it expects, and optionally a
        default `widget_id`. Fill a report template with create_report (`template_id`, and
        content {"slots": {name: widget_id}}). Returns the template with its id."""
        return await templates.create(project_id, name, kind, slots, content)

    @mcp.tool
    @inject
    async def list_templates(
        project_id: Id, templates: FromDishka[TemplateService]
    ) -> Sequence[Template]:
        """List a project's report and dashboard templates with their slots, oldest first.
        Look here before writing a report from scratch: filling a template keeps reports
        of the same kind alike."""
        return await templates.list(project_id)


async def _run(
    runs: RunService, project_id: Id, run_id: Id | None, time_range: TimeRange | None, actor: Actor
) -> Run:
    if run_id is not None:
        return await runs.get(run_id)
    return await runs.start(project_id, actor, time_range)


async def _view(reports: ReportService, version: ReportVersion) -> ReportView:
    report = await reports.get(version.report_id)
    return _shown(report, version, await reports.versions(report.id))


def _shown(report: Report, version: ReportVersion, versions: Sequence[ReportVersion]) -> ReportView:
    return ReportView(
        report=report,
        version=version,
        versions=tuple(v.version for v in versions),
        url=report_url(report, version),
    )
