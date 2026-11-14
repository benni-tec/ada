"""Repositories of alert rules and the alerts they raise."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import (
    add_row,
    fetch,
    json_object,
    newest_first,
    oldest_first,
    rows,
    update_row,
)
from ada.adapters.db.tables import AlertRow, AlertRuleRow
from ada.core.models.alerts import Alert, AlertRule, AlertState, Severity
from ada.core.models.base import Id, JsonObject
from ada.core.models.errors import NotFound
from ada.core.ports.repositories import AlertRepository, AlertRuleRepository


def _rule(row: AlertRuleRow) -> AlertRule:
    return AlertRule(
        id=row.id,
        project_id=row.project_id,
        dashboard_id=row.dashboard_id,
        name=row.name,
        operator_id=row.operator_id,
        formula=row.formula,
        key_columns=tuple(row.key_columns),
        severity=Severity(row.severity),
        check_interval_seconds=row.check_interval_seconds,
        max_data_age_seconds=row.max_data_age_seconds,
        alert_pipeline_id=row.alert_pipeline_id,
        enabled=row.enabled,
        created_at=row.created_at,
        last_checked_at=row.last_checked_at,
        revision=row.revision,
    )


def _rule_edit(rule: AlertRule) -> dict[str, Any]:
    """The columns an edit may change. `last_checked_at` belongs to the check, so an edit
    that read the rule before a check does not put the old time back."""
    return {
        "dashboard_id": rule.dashboard_id,
        "name": rule.name,
        "operator_id": rule.operator_id,
        "formula": json_object(rule.formula),
        "key_columns": list(rule.key_columns),
        "severity": rule.severity.value,
        "check_interval_seconds": rule.check_interval_seconds,
        "max_data_age_seconds": rule.max_data_age_seconds,
        "alert_pipeline_id": rule.alert_pipeline_id,
        "enabled": rule.enabled,
    }


class SqlAlertRuleRepository(AlertRuleRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> AlertRule:
        return _rule(await fetch(self.session, AlertRuleRow, id, "alert rule"))

    async def list(self, dashboard_id: Id) -> Sequence[AlertRule]:
        statement = oldest_first(AlertRuleRow, AlertRuleRow.dashboard_id == dashboard_id)
        return [_rule(row) for row in await rows(self.session, statement)]

    async def list_enabled(self) -> Sequence[AlertRule]:
        statement = oldest_first(AlertRuleRow, AlertRuleRow.enabled.is_(True))
        return [_rule(row) for row in await rows(self.session, statement)]

    async def add(self, rule: AlertRule) -> None:
        row = AlertRuleRow(
            id=rule.id,
            project_id=rule.project_id,
            created_at=rule.created_at,
            last_checked_at=rule.last_checked_at,
            **_rule_edit(rule),
        )
        await add_row(self.session, row)

    async def update(self, rule: AlertRule, expected_revision: int) -> AlertRule:
        row = await update_row(
            self.session, AlertRuleRow, "alert rule", rule.id, expected_revision, _rule_edit(rule)
        )
        return _rule(row)

    async def record_check(self, id: Id, at: datetime) -> None:
        # A plain UPDATE on the table, so the revision stays: a check never makes a
        # concurrent edit conflict.
        table = AlertRuleRow.__table__
        result = await self.session.execute(
            update(table).where(table.c.id == id).values(last_checked_at=at)
        )
        if result.rowcount == 0:
            raise NotFound("alert rule", id)


def _alert(row: AlertRow) -> Alert:
    return Alert(
        id=row.id,
        project_id=row.project_id,
        rule_id=row.rule_id,
        key=row.key,
        state=AlertState(row.state),
        since_run_id=row.since_run_id,
        last_run_id=row.last_run_id,
        started_at=row.started_at,
        resolved_at=row.resolved_at,
        condition_sql=row.condition_sql,
        pipeline_run_id=row.pipeline_run_id,
    )


def _alert_values(alert: Alert) -> dict[str, Any]:
    return {
        "key": json_object(alert.key),
        "state": alert.state.value,
        "since_run_id": alert.since_run_id,
        "last_run_id": alert.last_run_id,
        "started_at": alert.started_at,
        "resolved_at": alert.resolved_at,
        "condition_sql": alert.condition_sql,
        "pipeline_run_id": alert.pipeline_run_id,
    }


class SqlAlertRepository(AlertRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Alert:
        return _alert(await fetch(self.session, AlertRow, id, "alert"))

    async def add(self, alert: Alert) -> None:
        row = AlertRow(
            id=alert.id, project_id=alert.project_id, rule_id=alert.rule_id, **_alert_values(alert)
        )
        await add_row(self.session, row)

    async def save(self, alert: Alert) -> None:
        # Alerts carry no revision: only the check of one rule writes them, one at a time.
        table = AlertRow.__table__
        result = await self.session.execute(
            update(table).where(table.c.id == alert.id).values(**_alert_values(alert))
        )
        if result.rowcount == 0:
            raise NotFound("alert", alert.id)

    async def find(self, rule_id: Id, key: JsonObject) -> Alert | None:
        # JSONB equality: the same keys and values, whatever their order.
        row = await self.session.scalar(
            oldest_first(
                AlertRow,
                AlertRow.rule_id == rule_id,
                AlertRow.key == json_object(key),
                AlertRow.state == AlertState.FIRING.value,
                by=AlertRow.started_at,
            ).execution_options(populate_existing=True)
        )
        return _alert(row) if row is not None else None

    async def list(self, project_id: Id, state: AlertState | None = None) -> Sequence[Alert]:
        conditions = [AlertRow.project_id == project_id]
        if state is not None:
            conditions.append(AlertRow.state == state.value)
        statement = newest_first(AlertRow, AlertRow.started_at, *conditions)
        return [_alert(row) for row in await rows(self.session, statement)]
