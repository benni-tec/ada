from collections.abc import Sequence
from typing import Literal

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.alerts import Alert, AlertRule, AlertState, Severity
from ada.core.models.base import UNCHANGED, Change, DomainModel, Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.operators import OperatorId
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.projects import ProjectService
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId

# The fields of a rule that may be empty, which update_alert_rule can clear.
type Clearable = Literal["check_interval_seconds", "max_data_age_seconds", "alert_pipeline_id"]


class RuleCheck(DomainModel):
    rule: AlertRule
    # Alerts that started or resolved in this check.
    changed: Sequence[Alert]
    # Every alert of the rule that is firing now.
    firing: Sequence[Alert]


class FeedEntry(DomainModel):
    alert: Alert
    rule_name: str
    severity: Severity
    dashboard_id: Id
    # Where a person sees the feed in the frontend, relative to the host serving ADA.
    url: str


# Shown to the agent with create_alert_rule; update_alert_rule refers to it.
FORMULA_FORMAT = """
The formula is a JSON tree. Every node has an `id` (1 to 64 letters, digits, - or _),
unique in the tree, and a `kind`; composite nodes list their operands in `args`:

- {"id": "v", "kind": "column", "column": "value"}: a column of the measure's output.
- {"id": "c", "kind": "constant", "value": 80}: a number, text, true or false; add
  "type": "date" or "timestamp" for an ISO 8601 string such as "2024-01-01".
- {"id": "a", "kind": "arithmetic", "op": "+" | "-" | "*" | "/", "args": [x, y]}: numbers.
  Dividing by zero gives no value, which never alerts.
- {"id": "p", "kind": "compare", "op": "<" | "<=" | ">" | ">=" | "=" | "!=", "args": [x, y]}:
  two values of the same type.
- {"id": "b", "kind": "and" | "or", "args": [x, y, ...]} and {"kind": "not", "args": [x]}:
  conditions.
- Time functions, which need the measure's time role. A period is a row; the previous one
  is the row before it by the time role's start within the same key:
  {"kind": "previous", "args": [x], "periods": 1} (x that many periods earlier),
  {"kind": "change", "args": [x], "periods": 1} (x minus x that many periods earlier),
  {"kind": "rolling_mean", "args": [x], "periods": 3} (the mean of x over the last n
  periods, this one included; unknown until n periods exist).

The root must be a condition. It is evaluated on each key's latest period (on every row
when the measure has no time role); earlier periods only feed the time functions.
Values withheld by a measure's `suppressed` flag never alert.

Example, "below 80, or down 5 points on the previous period":
{"id": "root", "kind": "or", "args": [
  {"id": "low", "kind": "compare", "op": "<", "args": [
    {"id": "v1", "kind": "column", "column": "value"},
    {"id": "c80", "kind": "constant", "value": 80}]},
  {"id": "drop", "kind": "compare", "op": "<=", "args": [
    {"id": "chg", "kind": "change", "periods": 1, "args": [
      {"id": "v2", "kind": "column", "column": "value"}]},
    {"id": "c5", "kind": "constant", "value": -5}]}]}
"""


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool(description=_create_description())
    @inject
    async def create_alert_rule(
        session_id: SessionId,
        dashboard_id: Id,
        name: str,
        operator_id: OperatorId,
        formula: JsonObject,
        key_columns: list[str],
        service: FromDishka[AlertService],
        severity: Severity = Severity.WARNING,
        check_interval_seconds: int | None = None,
        max_data_age_seconds: int | None = None,
        alert_pipeline_id: OperatorId | None = None,
    ) -> AlertRule:
        return await service.create_rule(
            dashboard_id,
            name,
            operator_id,
            formula,
            key_columns,
            severity=severity,
            check_interval_seconds=check_interval_seconds,
            max_data_age_seconds=max_data_age_seconds,
            alert_pipeline_id=alert_pipeline_id,
        )

    @mcp.tool
    @inject
    async def list_alert_rules(
        session_id: SessionId, dashboard_id: Id, service: FromDishka[AlertService]
    ) -> Sequence[AlertRule]:
        """List a dashboard's alert rules, each with its formula, key columns, severity,
        check interval, whether it is enabled and when it was last checked. Use it before
        adding a rule, to change one, or to see why something alerts."""
        return await service.list_rules(dashboard_id)

    @mcp.tool
    @inject
    async def get_alert_rule(
        session_id: SessionId, rule_id: Id, service: FromDishka[AlertService]
    ) -> AlertRule:
        """Read one alert rule with its current `revision`, which update_alert_rule needs."""
        return await service.get_rule(rule_id)

    @mcp.tool
    @inject
    async def update_alert_rule(
        session_id: SessionId,
        rule_id: Id,
        expected_revision: int,
        service: FromDishka[AlertService],
        name: str | None = None,
        formula: JsonObject | None = None,
        severity: Severity | None = None,
        check_interval_seconds: int | None = None,
        enabled: bool | None = None,
        key_columns: Sequence[str] | None = None,
        max_data_age_seconds: int | None = None,
        alert_pipeline_id: OperatorId | None = None,
        clear: Sequence[Clearable] = (),
    ) -> AlertRule:
        """Change an alert rule: its name, formula (same format as in create_alert_rule),
        severity, check interval, key columns, maximum data age, alert pipeline, or whether
        it is enabled. Pass the `revision` you last read as `expected_revision`; if someone
        changed the rule since, this fails and you read it again. Fields left out stay as
        they are. To empty a field that may be empty, name it in `clear`: no interval
        checks whenever the data changes, no maximum age leaves freshness to the sources,
        no alert pipeline runs nothing when an alert fires. The measure cannot change:
        create a new rule for that. New key columns resolve the alerts of the old keys at
        the next check.

        Alerts follow the new formula from the next check; call check_alert_rule to check
        now. Returns the rule with its new revision."""
        given = {
            "check_interval_seconds": check_interval_seconds,
            "max_data_age_seconds": max_data_age_seconds,
            "alert_pipeline_id": alert_pipeline_id,
        }
        both = [field for field in clear if given[field] is not None]
        if both:
            raise Invalid(f"Either set or clear a field, not both: {', '.join(both)}")

        def change[T](field: Clearable, value: T | None) -> Change[T | None]:
            if field in clear:
                return None
            return value if value is not None else UNCHANGED

        return await service.update_rule(
            rule_id,
            expected_revision,
            name=name,
            formula=formula,
            severity=severity,
            check_interval_seconds=change("check_interval_seconds", check_interval_seconds),
            enabled=enabled,
            key_columns=key_columns,
            max_data_age_seconds=change("max_data_age_seconds", max_data_age_seconds),
            alert_pipeline_id=change("alert_pipeline_id", alert_pipeline_id),
        )

    @mcp.tool
    @inject
    async def check_alert_rule(
        session_id: SessionId, rule_id: Id, service: FromDishka[AlertService]
    ) -> RuleCheck:
        """Check an alert rule now instead of waiting for its interval: start a new run of
        its measure, evaluate the formula, and open, keep or resolve one alert per key.
        Sources older than the rule's maximum data age are fetched again first. Returns
        the alerts that changed in this check and every alert of the rule firing now;
        each alert's `last_run_id` is the run whose data shows the condition."""
        changed = await service.check(rule_id)
        rule = await service.get_rule(rule_id)
        firing = [
            alert
            for alert in await service.alerts(rule.project_id, AlertState.FIRING)
            if alert.rule_id == rule.id
        ]
        return RuleCheck(rule=rule, changed=changed, firing=firing)

    @mcp.tool
    @inject
    async def list_alerts(
        project_id: Id,
        session_id: SessionId,
        projects: FromDishka[ProjectService],
        service: FromDishka[AlertService],
        state: AlertState | None = None,
    ) -> Sequence[FeedEntry]:
        """The project's alert feed: firing alerts first, newest first. Filter with `state`
        ("firing" or "resolved"). Each entry has the alert's key (e.g. which region),
        since when it fires, the run that first and last showed it, and its rule's name,
        severity and dashboard. Give the person the `url` to see the feed."""
        await projects.get(project_id)
        alerts = await service.alerts(project_id, state)
        rules: dict[Id, AlertRule] = {}
        entries: list[FeedEntry] = []
        for alert in sorted(alerts, key=lambda alert: alert.state is not AlertState.FIRING):
            if alert.rule_id not in rules:
                rules[alert.rule_id] = await service.get_rule(alert.rule_id)
            rule = rules[alert.rule_id]
            entries.append(
                FeedEntry(
                    alert=alert,
                    rule_name=rule.name,
                    severity=rule.severity,
                    dashboard_id=rule.dashboard_id,
                    url=f"/projects/{project_id}/alerts",
                )
            )
        return entries


def _create_description() -> str:
    return (
        "Add an alert rule to a dashboard: a condition on the rows of a measure pipeline "
        "(`operator_id`, e.g. screening coverage by region and year), checked on its own "
        'interval. One alert is kept per key (`key_columns`, e.g. ["region"]), so a region '
        "that stays below target alerts once, not on every check.\n\n"
        "`check_interval_seconds` sets how often it is checked; without one it is checked "
        "whenever the measure's data changes. `max_data_age_seconds` forces a refetch of "
        "older source data before a check. `alert_pipeline_id` names a pipeline with one "
        "input slot that runs on the alerting rows whenever a new alert fires.\n\n"
        "A formula that does not fit the measure's columns fails with a message naming the "
        "node at fault. Returns the rule; call check_alert_rule to check it at once.\n"
        + FORMULA_FORMAT
    )
