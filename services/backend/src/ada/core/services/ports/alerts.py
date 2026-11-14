from collections.abc import Sequence
from typing import Protocol

from ada.core.models.alerts import Alert, AlertRule, AlertState, Severity
from ada.core.models.base import Id, JsonObject
from ada.core.models.operators import OperatorId


class AlertService(Protocol):
    async def create_rule(
        self,
        dashboard_id: Id,
        name: str,
        operator_id: OperatorId,
        formula: JsonObject,
        key_columns: Sequence[str],
        severity: Severity = Severity.WARNING,
        check_interval_seconds: int | None = None,
        max_data_age_seconds: int | None = None,
        alert_pipeline_id: OperatorId | None = None,
    ) -> AlertRule:
        """Raises Invalid when the formula does not compile against the operator's
        schema, or a key column does not exist."""
        ...

    async def get_rule(self, id: Id) -> AlertRule: ...
    async def list_rules(self, dashboard_id: Id) -> Sequence[AlertRule]: ...

    async def update_rule(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        formula: JsonObject | None = None,
        severity: Severity | None = None,
        check_interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> AlertRule:
        """Change the given fields; None leaves a field as it is."""
        ...

    async def check(self, rule_id: Id) -> Sequence[Alert]:
        """Evaluate the rule on a new run of its measure pipeline. Returns the alerts whose
        state changed: newly firing ones and resolved ones. A key that keeps alerting
        keeps its alert."""
        ...

    async def due(self) -> Sequence[AlertRule]:
        """The enabled rules whose check interval has passed."""
        ...

    async def alerts(self, project_id: Id, state: AlertState | None = None) -> Sequence[Alert]: ...
