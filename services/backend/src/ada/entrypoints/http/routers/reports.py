"""Reports, their versions and sources lists, and templates (docs/contracts/wave2-reports.md)."""

from collections.abc import Sequence
from datetime import datetime

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status
from pydantic import TypeAdapter

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Conflict
from ada.core.models.operators import OperatorId
from ada.core.models.reports import Report, ReportVersion, Template, TemplateKind, VersionBump
from ada.core.models.runs import Run
from ada.core.models.sources import AccessKind, DataFormat
from ada.core.models.time import TimeRange
from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.ports.runs import RunService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["reports"])


class NewReport(Request):
    """A report and its first version, 1.0.0. `content` is a component tree, or
    `{"slots": {name: widget_id}}` with `template_id` to fill a report template. Without
    `run_id` a run is started for `time_range`; with one, the range is the run's."""

    name: str
    content: JsonObject
    run_id: Id | None = None
    time_range: TimeRange | None = None
    session_id: Id | None = None
    dashboard_id: Id | None = None
    template_id: Id | None = None


class NewReportVersion(Request):
    """The next version. Without `bump` the platform picks the level from what changed.
    With `expected_revision`, the version is only added if nobody else added one since the
    report was read at that revision. Without `run_id` a run is started for
    `time_range`, which gives the latest data."""

    content: JsonObject
    run_id: Id | None = None
    time_range: TimeRange | None = None
    bump: VersionBump | None = None
    expected_revision: int | None = None


class GeneratedReport(Request):
    """Freeze the dashboard's current widgets at a run. Without `run_id` a run is started
    for `time_range`, or else for the dashboard's default range."""

    name: str
    run_id: Id | None = None
    time_range: TimeRange | None = None


class NewTemplate(Request):
    name: str
    kind: TemplateKind
    slots: tuple[Slot, ...]
    content: JsonObject | None = None


class ReportSource(DomainModel):
    """One data source behind a report version's widgets, as the version's run read it."""

    data_source_id: Id
    name: str
    # Where the data was fetched from when the version was made.
    address: str
    access_kind: AccessKind
    format: DataFormat
    operator_id: OperatorId
    snapshot_id: Id | None = None
    fetched_at: datetime | None = None
    content_hash: str | None = None
    widget_ids: tuple[Id, ...]


_sources = TypeAdapter(tuple[ReportSource, ...])


@router.get("/projects/{project_id}/reports")
async def list_reports(
    project_id: Id,
    service: FromDishka[ReportService],
    session_id: Id | None = None,
    dashboard_id: Id | None = None,
) -> Sequence[Report]:
    """The project's reports, oldest first; with `session_id` or `dashboard_id` only the
    ones that session or dashboard produced."""
    return [
        report
        for report in await service.list(project_id)
        if (session_id is None or report.session_id == session_id)
        and (dashboard_id is None or report.dashboard_id == dashboard_id)
    ]


@router.post("/projects/{project_id}/reports", status_code=status.HTTP_201_CREATED)
async def create_report(
    project_id: Id,
    body: NewReport,
    service: FromDishka[ReportService],
    runs: FromDishka[RunService],
) -> ReportVersion:
    run = await _run(runs, project_id, body.run_id, body.time_range)
    return await service.create(
        project_id,
        body.name,
        body.content,
        run.id,
        body.time_range if body.time_range is not None else run.time_range,
        WEB,
        session_id=body.session_id,
        dashboard_id=body.dashboard_id,
        template_id=body.template_id,
    )


@router.get("/reports/{report_id}")
async def get_report(report_id: Id, service: FromDishka[ReportService]) -> Report:
    return await service.get(report_id)


@router.get("/reports/{report_id}/versions")
async def list_report_versions(
    report_id: Id, service: FromDishka[ReportService]
) -> Sequence[ReportVersion]:
    """Every version, lowest version number first."""
    return await service.versions(report_id)


@router.post("/reports/{report_id}/versions", status_code=status.HTTP_201_CREATED)
async def add_report_version(
    report_id: Id,
    body: NewReportVersion,
    service: FromDishka[ReportService],
    runs: FromDishka[RunService],
) -> ReportVersion:
    report = await service.get(report_id)
    # The port takes no revision; checking it here still turns a version someone else
    # added since the client read the report into a 409. Two versions racing past this
    # check conflict on the report's own revision inside the service.
    if body.expected_revision is not None and report.revision != body.expected_revision:
        raise Conflict("report", report_id, body.expected_revision, report.revision)
    run = await _run(runs, report.project_id, body.run_id, body.time_range)
    time_range = body.time_range if body.time_range is not None else run.time_range
    return await service.add_version(
        report_id, body.content, run.id, time_range, WEB, bump=body.bump
    )


@router.get("/report-versions/{version_id}")
async def get_report_version(version_id: Id, service: FromDishka[ReportService]) -> ReportVersion:
    return await service.version(version_id)


@router.get("/report-versions/{version_id}/sources")
async def list_report_sources(
    version_id: Id, service: FromDishka[ReportService]
) -> Sequence[ReportSource]:
    """The data sources behind the version's widgets, with the address and fetch time of
    the snapshot its run used. Generated when the version was made."""
    version = await service.version(version_id)
    return _sources.validate_python(version.content.get("sources", []))


@router.post("/dashboards/{dashboard_id}/reports", status_code=status.HTTP_201_CREATED)
async def generate_report(
    dashboard_id: Id, body: GeneratedReport, service: FromDishka[ReportService]
) -> ReportVersion:
    """A report of the dashboard's current widgets at one run; a new version when the
    dashboard already has a report of that name."""
    return await service.generate_from_dashboard(
        dashboard_id, body.name, WEB, run_id=body.run_id, time_range=body.time_range
    )


@router.get("/projects/{project_id}/templates")
async def list_templates(
    project_id: Id, service: FromDishka[TemplateService]
) -> Sequence[Template]:
    return await service.list(project_id)


@router.post("/projects/{project_id}/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    project_id: Id, body: NewTemplate, service: FromDishka[TemplateService]
) -> Template:
    return await service.create(project_id, body.name, body.kind, body.slots, body.content)


@router.get("/templates/{template_id}")
async def get_template(template_id: Id, service: FromDishka[TemplateService]) -> Template:
    return await service.get(template_id)


async def _run(
    runs: RunService, project_id: Id, run_id: Id | None, time_range: TimeRange | None
) -> Run:
    """The run to pin: the one named, or a new one for the range."""
    if run_id is not None:
        return await runs.get(run_id)
    return await runs.start(project_id, WEB, time_range)
