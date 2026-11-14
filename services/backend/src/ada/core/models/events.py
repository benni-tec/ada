from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject


class EventType(StrEnum):
    """What the live stream carries. The payload names ids only, and clients fetch the rest;
    agent.turn_part is the exception."""

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
    AGENT_TURN_STARTED = "agent.turn_started"
    # The one event that carries content (a part of the agent's answer), and the one sent
    # before a commit: token deltas cannot be fetched afterwards.
    AGENT_TURN_PART = "agent.turn_part"
    AGENT_TURN_FINISHED = "agent.turn_finished"


class Event(DomainModel):
    type: EventType
    project_id: Id
    payload: JsonObject = {}
    at: datetime
