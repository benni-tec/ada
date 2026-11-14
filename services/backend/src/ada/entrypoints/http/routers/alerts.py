from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.alerts import Alert, AlertRule, AlertState, Severity
from ada.core.models.base import UNCHANGED, Change, DomainModel, Id, JsonObject
from ada.core.models.dashboards import Dashboard
from ada.core.models.operators import OperatorId
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.projects import ProjectService
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["alerts"])


class NewAlertRule(Request):
    name: str
    # The measure pipeline: the operator whose rows the formula is evaluated on.
    operator_id: OperatorId
    # The condition as a formula tree (docs/contracts.md, "Alerts").
    formula: JsonObject
    # The columns that identify what a row is about; one alert per key.
    key_columns: list[str]
    severity: Severity = Severity.WARNING
    check_interval_seconds: int | None = None
    max_data_age_seconds: int | None = None
    alert_pipeline_id: OperatorId | None = None


class AlertRuleChange(Request):
    """Fields left out stay as they are. The interval, maximum age and alert pipeline may
    be empty: null clears them (an interval of null checks whenever the data changes)."""

    expected_revision: int
    name: str | None = None
    formula: JsonObject | None = None
    severity: Severity | None = None
    check_interval_seconds: int | None = None
    enabled: bool | None = None
    key_columns: list[str] | None = None
    max_data_age_seconds: int | None = None
    alert_pipeline_id: OperatorId | None = None

    def given[T](self, field: str, value: T) -> Change[T]:
        """The value of a field that may be empty: null when sent as null, UNCHANGED when
        left out of the body."""
        return value if field in self.model_fields_set else UNCHANGED


class AlertView(DomainModel):
    """An alert with the rule that raised it, so a feed needs no request per rule."""

    alert: Alert
    rule: AlertRule


class CheckResult(DomainModel):
    # The rule after the check, with its new last_checked_at.
    rule: AlertRule
    # Alerts that started or resolved in this check.
    changed: Sequence[Alert]
    # Every alert of the rule that is firing now.
    firing: Sequence[Alert]


class DashboardRules(DomainModel):
    dashboard: Dashboard
    rules: Sequence[AlertRule]


@router.get("/dashboards/{dashboard_id}/alert-rules")
async def list_alert_rules(
    dashboard_id: Id, service: FromDishka[AlertService]
) -> Sequence[AlertRule]:
    return await service.list_rules(dashboard_id)


@router.post("/dashboards/{dashboard_id}/alert-rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    dashboard_id: Id, body: NewAlertRule, service: FromDishka[AlertService]
) -> AlertRule:
    """Add a rule to a dashboard. A formula that does not fit the measure's columns is a
    422 whose detail names the node at fault: `Formula node '<id>': ...`."""
    return await service.create_rule(
        dashboard_id,
        body.name,
        body.operator_id,
        body.formula,
        body.key_columns,
        severity=body.severity,
        check_interval_seconds=body.check_interval_seconds,
        max_data_age_seconds=body.max_data_age_seconds,
        alert_pipeline_id=body.alert_pipeline_id,
    )


@router.get("/alert-rules/{rule_id}")
async def get_alert_rule(rule_id: Id, service: FromDishka[AlertService]) -> AlertRule:
    return await service.get_rule(rule_id)


@router.patch("/alert-rules/{rule_id}")
async def update_alert_rule(
    rule_id: Id, body: AlertRuleChange, service: FromDishka[AlertService]
) -> AlertRule:
    return await service.update_rule(
        rule_id,
        body.expected_revision,
        name=body.name,
        formula=body.formula,
        severity=body.severity,
        check_interval_seconds=body.given("check_interval_seconds", body.check_interval_seconds),
        enabled=body.enabled,
        key_columns=body.key_columns,
        max_data_age_seconds=body.given("max_data_age_seconds", body.max_data_age_seconds),
        alert_pipeline_id=body.given("alert_pipeline_id", body.alert_pipeline_id),
    )


@router.post("/alert-rules/{rule_id}/check")
async def check_alert_rule(rule_id: Id, service: FromDishka[AlertService]) -> CheckResult:
    """Check the rule now, in this request, on a new run of its measure. A person who
    asks wants the answer; scheduled checks go through the worker."""
    changed = await service.check(rule_id)
    rule = await service.get_rule(rule_id)
    return CheckResult(rule=rule, changed=changed, firing=await _firing(service, rule))


@router.get("/projects/{project_id}/alert-rules")
async def list_project_alert_rules(
    project_id: Id,
    projects: FromDishka[ProjectService],
    dashboards: FromDishka[DashboardService],
    service: FromDishka[AlertService],
) -> Sequence[DashboardRules]:
    """Every dashboard of the project with its rules, dashboards oldest first."""
    await projects.get(project_id)
    return [
        DashboardRules(dashboard=dashboard, rules=await service.list_rules(dashboard.id))
        for dashboard in await dashboards.list(project_id)
    ]


@router.get("/projects/{project_id}/alerts")
async def list_alerts(
    project_id: Id,
    projects: FromDishka[ProjectService],
    service: FromDishka[AlertService],
    state: AlertState | None = None,
) -> Sequence[AlertView]:
    """The project's alert feed: firing alerts first, newest first within each state."""
    await projects.get(project_id)
    return await _views(service, await service.alerts(project_id, state))


@router.get("/dashboards/{dashboard_id}/alerts")
async def list_dashboard_alerts(
    dashboard_id: Id, service: FromDishka[AlertService], state: AlertState | None = None
) -> Sequence[AlertView]:
    """The alerts of the dashboard's rules, ordered like the project's feed; for the badges
    on a dashboard."""
    rules = await service.list_rules(dashboard_id)
    if not rules:
        return []
    ids = {rule.id for rule in rules}
    alerts = await service.alerts(rules[0].project_id, state)
    return await _views(service, [alert for alert in alerts if alert.rule_id in ids])


async def _views(service: AlertService, alerts: Sequence[Alert]) -> list[AlertView]:
    rules: dict[Id, AlertRule] = {}
    views: list[AlertView] = []
    for alert in alerts:
        if alert.rule_id not in rules:
            rules[alert.rule_id] = await service.get_rule(alert.rule_id)
        views.append(AlertView(alert=alert, rule=rules[alert.rule_id]))
    # Stable: the repository's newest-first order holds within each state.
    return sorted(views, key=lambda view: view.alert.state is not AlertState.FIRING)


async def _firing(service: AlertService, rule: AlertRule) -> list[Alert]:
    return [
        alert
        for alert in await service.alerts(rule.project_id, AlertState.FIRING)
        if alert.rule_id == rule.id
    ]
