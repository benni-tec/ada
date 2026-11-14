from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.reports import (
    Report,
    ReportSource,
    ReportVersion,
    Template,
    TemplateKind,
    VersionBump,
)
from ada.core.models.time import TimeRange


class ReportService(Protocol):
    async def get(self, id: Id) -> Report: ...
    async def list(self, project_id: Id) -> Sequence[Report]: ...
    async def version(self, version_id: Id) -> ReportVersion: ...
    async def versions(self, id: Id) -> Sequence[ReportVersion]: ...

    async def sources(self, version_id: Id) -> Sequence[ReportSource]:
        """The data sources behind a version's widgets, ordered by name, with the address
        and the snapshot its run read. Generated when the version was made."""
        ...

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
        """A new report with its first version, 1.0.0. Exactly one of session_id and
        dashboard_id names its owner."""
        ...

    async def add_version(
        self,
        id: Id,
        content: JsonObject,
        run_id: Id,
        time_range: TimeRange,
        actor: Actor,
        bump: VersionBump | None = None,
    ) -> ReportVersion:
        """The next version of a report. Without `bump` the level follows from what
        changed against the latest version: the widgets' pipelines (major), the run or
        time range (minor), or only static content (patch)."""
        ...

    async def generate_from_dashboard(
        self,
        dashboard_id: Id,
        name: str,
        actor: Actor,
        run_id: Id | None = None,
        time_range: TimeRange | None = None,
    ) -> ReportVersion:
        """Freeze a dashboard into a report: its current version's widgets at one run and
        time range. Adds a version when the dashboard already has a report of that name."""
        ...


class TemplateService(Protocol):
    async def create(
        self,
        project_id: Id,
        name: str,
        kind: TemplateKind,
        slots: Sequence[Slot],
        content: JsonObject | None = None,
    ) -> Template: ...

    async def get(self, id: Id) -> Template: ...
    async def list(self, project_id: Id) -> Sequence[Template]: ...
