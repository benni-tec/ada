from datetime import datetime
from enum import StrEnum

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import OperatorId


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertRule(DomainModel):
    """A condition on the output of a measure pipeline, checked on its own interval."""

    id: Id
    project_id: Id
    dashboard_id: Id
    name: str
    # The measure pipeline whose rows the formula is evaluated on.
    operator_id: OperatorId
    # The condition as a formula tree; a row alerts when it is true for that row.
    formula: JsonObject
    # The columns that identify what a row is about, e.g. region and indicator.
    key_columns: tuple[str, ...]
    severity: Severity = Severity.WARNING
    # None: check whenever the measure's data changes.
    check_interval_seconds: int | None = None
    # Force a source refresh for a check when its snapshot is older than this.
    max_data_age_seconds: int | None = None
    # Runs when the rule fires, with the alerting rows bound to its input.
    alert_pipeline_id: OperatorId | None = None
    enabled: bool = True
    created_at: datetime
    # Written by the check itself, outside the revision: a check never conflicts with an edit.
    last_checked_at: datetime | None = None
    revision: int = 1


class AlertState(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class Alert(DomainModel):
    """One instance per rule and key. A region that stays below target alerts once."""

    id: Id
    project_id: Id
    rule_id: Id
    # The key columns' values for this instance.
    key: JsonObject
    state: AlertState
    # The run that first showed the condition, and the latest one that still did.
    since_run_id: Id
    last_run_id: Id
    started_at: datetime
    resolved_at: datetime | None = None
