from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject


class EventType(StrEnum):
    """What the live stream carries. The payload names ids only; clients fetch the rest."""

    SESSION_CREATED = "session.created"
    SESSION_ENTRY_ADDED = "session.entry_added"
    WIDGET_CREATED = "widget.created"
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    RUN_FAILED = "run.failed"
    SOURCE_REFRESHED = "source.refreshed"
    SOURCE_REFRESH_FAILED = "source.refresh_failed"
    DASHBOARD_CHANGED = "dashboard.changed"
    REPORT_VERSION_CREATED = "report.version_created"
    ALERT_FIRING = "alert.firing"
    ALERT_RESOLVED = "alert.resolved"


class Event(DomainModel):
    type: EventType
    project_id: Id
    payload: JsonObject = {}
    at: datetime
