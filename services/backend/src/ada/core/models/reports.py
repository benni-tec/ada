from datetime import datetime
from enum import StrEnum

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.time import TimeRange


class TemplateKind(StrEnum):
    REPORT = "report"
    DASHBOARD = "dashboard"


class VersionBump(StrEnum):
    # Structure or pipelines changed; numbers are not comparable with the previous version.
    MAJOR = "major"
    # The same report on a new run or time range.
    MINOR = "minor"
    # Same run and data; only static content changed.
    PATCH = "patch"


class Template(DomainModel):
    id: Id
    project_id: Id
    name: str
    kind: TemplateKind
    slots: tuple[Slot, ...] = ()
    # For a report: the component tree with its static parts and its slots.
    content: JsonObject = {}
    created_at: datetime
    revision: int = 1


class Report(DomainModel):
    """A name with versions. Owned by the session or the dashboard that produced it."""

    id: Id
    project_id: Id
    name: str
    session_id: Id | None = None
    dashboard_id: Id | None = None
    latest_version_id: Id | None = None
    created_at: datetime
    revision: int = 1


class ReportVersion(DomainModel):
    """Immutable, and frozen at a run: it always shows the same numbers."""

    id: Id
    report_id: Id
    # Semantic version. Major: structure or pipelines changed. Minor: a new run or time
    # range. Patch: only static content changed.
    version: str
    run_id: Id
    time_range: TimeRange
    # The component tree. Only widget components carry data, by widget id.
    content: JsonObject
    template_id: Id | None = None
    dashboard_version_id: Id | None = None
    created_by: Actor
    created_at: datetime
