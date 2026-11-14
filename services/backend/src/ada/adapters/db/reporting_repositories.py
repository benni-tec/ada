"""Repositories of what is shown and reported: dashboards, templates and reports, with the
immutable versions of dashboards and reports."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import (
    add_row,
    dump,
    dump_all,
    fetch,
    json_object,
    oldest_first,
    require,
    rows,
    update_row,
)
from ada.adapters.db.tables import (
    DashboardRow,
    DashboardVersionRow,
    ReportRow,
    ReportVersionRow,
    TemplateRow,
)
from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.reports import Report, ReportVersion, Template, TemplateKind
from ada.core.models.time import TimeRange
from ada.core.ports.repositories import (
    DashboardRepository,
    ReportRepository,
    TemplateRepository,
)


def _dashboard(row: DashboardRow) -> Dashboard:
    return Dashboard(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        current_version_id=row.current_version_id,
        default_time_range=TimeRange(start=row.default_time_start, end=row.default_time_end),
        created_at=row.created_at,
        revision=row.revision,
    )


def _dashboard_edit(dashboard: Dashboard) -> dict[str, object]:
    return {
        "name": dashboard.name,
        "current_version_id": dashboard.current_version_id,
        "default_time_start": dashboard.default_time_range.start,
        "default_time_end": dashboard.default_time_range.end,
    }


def _dashboard_version(row: DashboardVersionRow) -> DashboardVersion:
    return DashboardVersion(
        id=row.id,
        dashboard_id=row.dashboard_id,
        number=row.number,
        slots=tuple(Slot.model_validate(slot) for slot in row.slots),
        template_id=row.template_id,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )


class SqlDashboardRepository(DashboardRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Dashboard:
        return _dashboard(await fetch(self.session, DashboardRow, id, "dashboard"))

    async def list(self, project_id: Id) -> Sequence[Dashboard]:
        statement = oldest_first(DashboardRow, DashboardRow.project_id == project_id)
        return [_dashboard(row) for row in await rows(self.session, statement)]

    async def add(self, dashboard: Dashboard) -> None:
        row = DashboardRow(
            id=dashboard.id,
            project_id=dashboard.project_id,
            created_at=dashboard.created_at,
            **_dashboard_edit(dashboard),
        )
        await add_row(self.session, row)

    async def update(self, dashboard: Dashboard, expected_revision: int) -> Dashboard:
        row = await update_row(
            self.session,
            DashboardRow,
            "dashboard",
            dashboard.id,
            expected_revision,
            _dashboard_edit(dashboard),
        )
        return _dashboard(row)

    async def add_version(self, version: DashboardVersion) -> None:
        await require(self.session, DashboardRow, version.dashboard_id, "dashboard")
        row = DashboardVersionRow(
            id=version.id,
            dashboard_id=version.dashboard_id,
            number=version.number,
            slots=dump_all(version.slots),
            template_id=version.template_id,
            created_by=dump(version.created_by),
            created_at=version.created_at,
        )
        await add_row(self.session, row)

    async def get_version(self, id: Id) -> DashboardVersion:
        row = await fetch(self.session, DashboardVersionRow, id, "dashboard version")
        return _dashboard_version(row)

    async def versions(self, dashboard_id: Id) -> Sequence[DashboardVersion]:
        statement = (
            select(DashboardVersionRow)
            .where(DashboardVersionRow.dashboard_id == dashboard_id)
            .order_by(DashboardVersionRow.number)
        )
        return [_dashboard_version(row) for row in await rows(self.session, statement)]


def _template(row: TemplateRow) -> Template:
    return Template(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        kind=TemplateKind(row.kind),
        slots=tuple(Slot.model_validate(slot) for slot in row.slots),
        content=row.content,
        created_at=row.created_at,
        revision=row.revision,
    )


def _template_edit(template: Template) -> dict[str, object]:
    return {
        "name": template.name,
        "kind": template.kind.value,
        "slots": dump_all(template.slots),
        "content": json_object(template.content),
    }


class SqlTemplateRepository(TemplateRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Template:
        return _template(await fetch(self.session, TemplateRow, id, "template"))

    async def list(self, project_id: Id) -> Sequence[Template]:
        statement = oldest_first(TemplateRow, TemplateRow.project_id == project_id)
        return [_template(row) for row in await rows(self.session, statement)]

    async def add(self, template: Template) -> None:
        row = TemplateRow(
            id=template.id,
            project_id=template.project_id,
            created_at=template.created_at,
            **_template_edit(template),
        )
        await add_row(self.session, row)

    async def update(self, template: Template, expected_revision: int) -> Template:
        row = await update_row(
            self.session,
            TemplateRow,
            "template",
            template.id,
            expected_revision,
            _template_edit(template),
        )
        return _template(row)


def _report(row: ReportRow) -> Report:
    return Report(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        session_id=row.session_id,
        dashboard_id=row.dashboard_id,
        latest_version_id=row.latest_version_id,
        created_at=row.created_at,
        revision=row.revision,
    )


def _report_edit(report: Report) -> dict[str, object]:
    return {
        "name": report.name,
        "session_id": report.session_id,
        "dashboard_id": report.dashboard_id,
        "latest_version_id": report.latest_version_id,
    }


def _report_version(row: ReportVersionRow) -> ReportVersion:
    return ReportVersion(
        id=row.id,
        report_id=row.report_id,
        version=row.version,
        run_id=row.run_id,
        time_range=TimeRange(start=row.time_start, end=row.time_end),
        content=row.content,
        template_id=row.template_id,
        dashboard_version_id=row.dashboard_version_id,
        created_by=Actor.model_validate(row.created_by),
        created_at=row.created_at,
    )


class SqlReportRepository(ReportRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Report:
        return _report(await fetch(self.session, ReportRow, id, "report"))

    async def list(self, project_id: Id) -> Sequence[Report]:
        statement = oldest_first(ReportRow, ReportRow.project_id == project_id)
        return [_report(row) for row in await rows(self.session, statement)]

    async def add(self, report: Report) -> None:
        row = ReportRow(
            id=report.id,
            project_id=report.project_id,
            created_at=report.created_at,
            **_report_edit(report),
        )
        await add_row(self.session, row)

    async def update(self, report: Report, expected_revision: int) -> Report:
        row = await update_row(
            self.session, ReportRow, "report", report.id, expected_revision, _report_edit(report)
        )
        return _report(row)

    async def add_version(self, version: ReportVersion) -> None:
        await require(self.session, ReportRow, version.report_id, "report")
        row = ReportVersionRow(
            id=version.id,
            report_id=version.report_id,
            version=version.version,
            run_id=version.run_id,
            time_start=version.time_range.start,
            time_end=version.time_range.end,
            content=json_object(version.content),
            template_id=version.template_id,
            dashboard_version_id=version.dashboard_version_id,
            created_by=dump(version.created_by),
            created_at=version.created_at,
        )
        await add_row(self.session, row)

    async def get_version(self, id: Id) -> ReportVersion:
        return _report_version(await fetch(self.session, ReportVersionRow, id, "report version"))

    async def versions(self, report_id: Id) -> Sequence[ReportVersion]:
        statement = oldest_first(ReportVersionRow, ReportVersionRow.report_id == report_id)
        return [_report_version(row) for row in await rows(self.session, statement)]
