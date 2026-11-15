from datetime import datetime

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.time import TimeRange


class Slot(DomainModel):
    """A place on a dashboard or in a template."""

    name: str
    # On a dashboard template this is advice: what probably belongs here.
    description: str = ""
    widget_id: Id | None = None
    # Position and size in the grid.
    layout: JsonObject = {}


class Dashboard(DomainModel):
    """A live view that follows the latest run. Its content lives in its versions; this
    record only points at the current one."""

    id: Id
    project_id: Id
    name: str
    current_version_id: Id | None = None
    # The range shown until a viewer changes it.
    default_time_range: TimeRange = TimeRange()
    created_at: datetime
    revision: int = 1
    # Its place among the pinned dashboards; None when not pinned (listed after them, in
    # creation order). Only people pin, outside the revision.
    position: int | None = None


class DashboardVersion(DomainModel):
    """Immutable. Every edit of a dashboard adds one."""

    id: Id
    dashboard_id: Id
    number: int
    slots: tuple[Slot, ...] = ()
    template_id: Id | None = None
    created_by: Actor
    created_at: datetime
