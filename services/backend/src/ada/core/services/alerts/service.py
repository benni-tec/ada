import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import uuid7

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import Alert, AlertRule, AlertState, Severity
from ada.core.models.base import UNCHANGED, Change, Id, JsonObject
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.operators import (
    InputParams,
    Operator,
    OperatorId,
    OperatorKind,
    SourceParams,
)
from ada.core.models.runs import Run
from ada.core.models.schema import ColumnType, OutputKind, Schema
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    AlertRepository,
    AlertRuleRepository,
    DashboardRepository,
    OperatorRepository,
    RunRepository,
    SnapshotRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.alerts.formula import Compiled, compile_rule
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService

logger = logging.getLogger(__name__)

# Checks are platform work, whoever asked for one.
PLATFORM = Actor(kind=ActorKind.SYSTEM, name="ada")

# Alerting rows are one per key at most (with a time role), so this bounds the keys a rule
# may alert on at once. Past it, resolving would be guesswork; the check fails instead.
MAX_ALERTING_ROWS = 10_000


class Alerts(AlertService):
    """Alert rules and their checks.

    A check makes the rule's condition part of the lineage: the compiled condition is a
    transform over the measure operator (`alerting_operator`), so the alerting rows are that
    operator's output in the check's run, and an alert opens the exact rows that raised it.
    """

    def __init__(
        self,
        rules: AlertRuleRepository,
        alerts: AlertRepository,
        dashboards: DashboardRepository,
        operators: OperatorRepository,
        snapshots: SnapshotRepository,
        runs: RunRepository,
        pipelines: PipelineService,
        run_service: RunService,
        sources: SourceService,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.rules = rules
        self.instances = alerts
        self.dashboards = dashboards
        self.operators = operators
        self.snapshots = snapshots
        self.runs = runs
        self.pipelines = pipelines
        self.run_service = run_service
        self.sources = sources
        self.events = events
        self.clock = clock

    # Rules

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
        dashboard = await self.dashboards.get(dashboard_id)
        rule = AlertRule(
            id=uuid7(),
            project_id=dashboard.project_id,
            dashboard_id=dashboard.id,
            name=name.strip(),
            operator_id=operator_id,
            formula=formula,
            key_columns=tuple(key_columns),
            severity=severity,
            check_interval_seconds=check_interval_seconds,
            max_data_age_seconds=max_data_age_seconds,
            alert_pipeline_id=alert_pipeline_id,
            created_at=self.clock.now(),
        )
        measure = await self._check(rule)
        if alert_pipeline_id is not None:
            await self._alert_input(rule, measure)
        await self.rules.add(rule)
        return rule

    async def get_rule(self, id: Id) -> AlertRule:
        return await self.rules.get(id)

    async def list_rules(self, dashboard_id: Id) -> Sequence[AlertRule]:
        await self.dashboards.get(dashboard_id)
        return await self.rules.list(dashboard_id)

    async def update_rule(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        formula: JsonObject | None = None,
        severity: Severity | None = None,
        check_interval_seconds: Change[int | None] = UNCHANGED,
        enabled: bool | None = None,
        key_columns: Sequence[str] | None = None,
        max_data_age_seconds: Change[int | None] = UNCHANGED,
        alert_pipeline_id: Change[OperatorId | None] = UNCHANGED,
    ) -> AlertRule:
        rule = await self.rules.get(id)
        # None keeps a field that cannot be empty; UNCHANGED keeps one that can.
        kept = {
            "name": name.strip() if name is not None else None,
            "formula": formula,
            "severity": severity,
            "enabled": enabled,
            "key_columns": tuple(key_columns) if key_columns is not None else None,
        }
        clearable = {
            "check_interval_seconds": check_interval_seconds,
            "max_data_age_seconds": max_data_age_seconds,
            "alert_pipeline_id": alert_pipeline_id,
        }
        changes = {k: v for k, v in kept.items() if v is not None} | {
            k: v for k, v in clearable.items() if v is not UNCHANGED
        }
        updated = rule.model_copy(update=changes)
        measure = await self._check(updated)
        if updated.alert_pipeline_id is not None:
            await self._alert_input(updated, measure)
        return await self.rules.update(updated, expected_revision)

    async def _check(self, rule: AlertRule) -> Operator:
        """Raises Invalid for a rule that cannot be checked; returns its measure."""
        if not rule.name:
            raise Invalid("An alert rule needs a name")
        for field in ("check_interval_seconds", "max_data_age_seconds"):
            value = getattr(rule, field)
            if value is not None and value <= 0:
                raise Invalid(f"{field} must be positive")
        measure = await self._measure(rule)
        compiled = compile_rule(rule.formula, measure.output, rule.key_columns)
        # Describing the compiled query is the last word on whether it runs: it adds the
        # operator the checks will use, so a rule never names SQL that does not bind.
        await self._alerting_operator(rule, measure, compiled)
        return measure

    async def _measure(self, rule: AlertRule) -> Operator:
        try:
            measure = await self.operators.get(rule.operator_id)
        except NotFound:
            raise Invalid(f"Operator {rule.operator_id} does not exist") from None
        if measure.project_id != rule.project_id:
            raise Invalid(f"Operator {rule.operator_id} belongs to another project")
        if measure.output.kind is not OutputKind.TABLE:
            raise Invalid(f"Operator {rule.operator_id} does not produce a table")
        if not measure.output.columns:
            # A source registered without a schema: its columns are only known from data.
            raise Invalid(
                f"The columns of operator {rule.operator_id} are not declared; build the rule "
                "on a transform over it, e.g. SELECT * FROM input_0, whose columns are derived"
            )
        return measure

    async def _alerting_operator(
        self, rule: AlertRule, measure: Operator, compiled: Compiled | None = None
    ) -> Operator:
        """The transform whose output is the rule's alerting rows. The same rule definition
        is the same operator, so every check of an unchanged rule reuses it."""
        compiled = compiled or compile_rule(rule.formula, measure.output, rule.key_columns)
        return await self.pipelines.add_transform(
            rule.project_id,
            compiled.sql,
            [measure.id],
            PLATFORM,
            # The rows are the measure's rows, so its roles still hold.
            roles=measure.output.roles,
        )

    async def _alert_input(self, rule: AlertRule, measure: Operator) -> str:
        """The name of the one input slot of the rule's alert pipeline, which takes the
        alerting rows; they have the measure's columns."""
        assert rule.alert_pipeline_id is not None
        try:
            pipeline = await self.operators.get(rule.alert_pipeline_id)
        except NotFound:
            raise Invalid(f"The alert pipeline {rule.alert_pipeline_id} does not exist") from None
        if pipeline.project_id != rule.project_id:
            raise Invalid(f"The alert pipeline {pipeline.id} belongs to another project")
        upstream = await self.operators.upstream(pipeline.id)
        slots = [op for op in upstream if op.kind is OperatorKind.INPUT]
        names = {InputParams.model_validate(op.params).name for op in slots}
        if len(names) != 1:
            raise Invalid(
                f"An alert pipeline needs exactly one input for the alerting rows; "
                f"{pipeline.id} has {len(names)}"
            )
        for slot in slots:
            _check_fits(slot.output, measure.output, InputParams.model_validate(slot.params).name)
        return names.pop()

    # Checks

    async def check(self, rule_id: Id) -> Sequence[Alert]:
        rule = await self.rules.get(rule_id)
        # Recorded as the time the check started: data that arrives while it runs is newer
        # than the check, so a rule without an interval is due again for it.
        started = self.clock.now()
        measure = await self._measure(rule)
        alerting = await self._alerting_operator(rule, measure)
        await self._demand_fresh_data(rule)

        # Everything that can fail runs before an alert is written, so a failed check
        # leaves the alerts as they were.
        run = await self.run_service.start(rule.project_id, PLATFORM)
        rows = await self.run_service.read(run.id, alerting.id, MAX_ALERTING_ROWS)
        if rows.truncated:
            raise Invalid(
                f"More than {MAX_ALERTING_ROWS} rows alert for rule {rule.id}; narrow the "
                "condition or the key"
            )
        names = [column.name for column in rows.columns]
        alerting_keys: dict[str, JsonObject] = {}
        for row in rows.rows:
            values = dict(zip(names, row, strict=True))
            key = {column: _json_value(values[column]) for column in rule.key_columns}
            alerting_keys.setdefault(_canonical(key), key)

        now = self.clock.now()
        firing = {
            _canonical(alert.key): alert
            for alert in await self.instances.list(rule.project_id, AlertState.FIRING)
            if alert.rule_id == rule.id
        }
        # The pipeline runs for alerts that start now; it does not fail the check, so it
        # can run before they are written, and they name its run.
        starting = [key for canonical, key in alerting_keys.items() if canonical not in firing]
        pipeline_run_id = (
            await self._run_alert_pipeline(rule, measure, alerting, run)
            if rule.alert_pipeline_id is not None and starting
            else None
        )
        started_alerts: list[Alert] = []
        resolved_alerts: list[Alert] = []
        for canonical, alert in firing.items():
            if canonical in alerting_keys:
                # Still alerting: the same instance, now also shown by this run (and by the
                # rule's current condition, should the formula have changed).
                await self.instances.save(
                    alert.model_copy(
                        update={"last_run_id": run.id, "condition_operator_id": alerting.id}
                    )
                )
            else:
                # last_run_id and the condition stay those of the last run that showed it.
                resolved = alert.model_copy(
                    update={"state": AlertState.RESOLVED, "resolved_at": now}
                )
                await self.instances.save(resolved)
                resolved_alerts.append(resolved)
        for key in starting:
            alert = Alert(
                id=uuid7(),
                project_id=rule.project_id,
                rule_id=rule.id,
                key=key,
                state=AlertState.FIRING,
                since_run_id=run.id,
                last_run_id=run.id,
                started_at=now,
                condition_operator_id=alerting.id,
                pipeline_run_id=pipeline_run_id,
            )
            await self.instances.add(alert)
            started_alerts.append(alert)

        changed = started_alerts + resolved_alerts
        for alert in changed:
            await self._publish(alert)
        await self.rules.record_check(rule.id, started)
        return changed

    async def _demand_fresh_data(self, rule: AlertRule) -> None:
        """Force a refresh of every source upstream whose data is older than the rule's
        maximum data age, overriding the source's own policy for this check."""
        if rule.max_data_age_seconds is None:
            return
        limit = timedelta(seconds=rule.max_data_age_seconds)
        now = self.clock.now()
        for operator in await self.operators.upstream(rule.operator_id):
            if operator.kind is not OperatorKind.SOURCE:
                continue
            source_id = SourceParams.model_validate(operator.params).data_source_id
            confirmed = await self._data_confirmed_at(operator, source_id)
            if confirmed is not None and now - confirmed < limit:
                continue
            try:
                await self.sources.refresh(source_id, force=True)
            except Exception as error:
                # The run serves the last good snapshot, as every run does after a failed
                # refresh; the failure is recorded on the source and announced.
                logger.warning(
                    "Rule %s wants data younger than %ss, but source %s failed to refresh: %s",
                    rule.id,
                    rule.max_data_age_seconds,
                    source_id,
                    error,
                )

    async def _data_confirmed_at(self, operator: Operator, source_id: Id) -> datetime | None:
        """When the source's data was last known current: its newest snapshot, or a later
        successful check that found the same content and so wrote none."""
        source = await self.sources.get(source_id)
        times = [snapshot.fetched_at for snapshot in await self.snapshots.list(operator.id)]
        if source.last_checked_at is not None and source.last_error is None:
            times.append(source.last_checked_at)
        return max(times, default=None)

    async def _run_alert_pipeline(
        self, rule: AlertRule, measure: Operator, alerting: Operator, check_run: Run
    ) -> Id | None:
        """Run the alert pipeline on the alerting rows, in a run of its own that fixes the
        check run's snapshots: the same data, but a binding marks a run as a scenario, and
        the check run must not be one. Returns the run, also when the pipeline failed in
        it (it says run.failed); None when no run started."""
        run_id: Id | None = None
        try:
            slot = await self._alert_input(rule, measure)
            run = await self.run_service.start(
                rule.project_id, PLATFORM, bindings={slot: alerting.id}
            )
            run_id = run.id
            fixed = await self.runs.get(check_run.id)
            for operator_id, snapshot_id in fixed.snapshots.items():
                await self.runs.fix_snapshot(run.id, operator_id, snapshot_id)
            assert rule.alert_pipeline_id is not None
            await self.run_service.execute(run.id, rule.alert_pipeline_id)
        except Exception:
            # The alerts stand without it.
            logger.exception("The alert pipeline of rule %s failed", rule.id)
        return run_id

    async def due(self) -> Sequence[AlertRule]:
        now = self.clock.now()
        due: list[AlertRule] = []
        for rule in await self.rules.list_enabled():
            if rule.last_checked_at is None:
                due.append(rule)
            elif rule.check_interval_seconds is not None:
                interval = timedelta(seconds=rule.check_interval_seconds)
                if now - rule.last_checked_at >= interval:
                    due.append(rule)
            elif await self._data_changed_since(rule.operator_id, rule.last_checked_at):
                due.append(rule)
        return due

    async def _data_changed_since(self, operator_id: OperatorId, at: datetime) -> bool:
        """Whether a source under the measure has a snapshot newer than `at`. A refresh
        writes a snapshot only when the content changed, so this reads no data and fetches
        nothing: one walk up the pipeline and one snapshot listing per source."""
        try:
            upstream = await self.operators.upstream(operator_id)
        except NotFound:
            return False
        for operator in upstream:
            if operator.kind is OperatorKind.SOURCE:
                snapshots = await self.snapshots.list(operator.id)
                if any(snapshot.fetched_at > at for snapshot in snapshots):
                    return True
        return False

    async def alerts(self, project_id: Id, state: AlertState | None = None) -> Sequence[Alert]:
        return await self.instances.list(project_id, state)

    async def _publish(self, alert: Alert) -> None:
        type = (
            EventType.ALERT_FIRING if alert.state is AlertState.FIRING else EventType.ALERT_RESOLVED
        )
        await self.events.publish(
            Event(
                type=type,
                project_id=alert.project_id,
                payload={"alert_id": str(alert.id), "rule_id": str(alert.rule_id)},
                at=self.clock.now(),
            )
        )


def _json_value(value: object) -> object:
    """A key value as JSON stores it, so a key read back from the database compares equal."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _canonical(key: JsonObject) -> str:
    return json.dumps(key, sort_keys=True, default=str)


def _check_fits(slot: Schema, measure: Schema, name: str) -> None:
    """Whether rows with the measure's columns fill the slot: every declared column is
    there with a fitting type; an integer fits where a number is declared."""
    problems: list[str] = []
    for wanted in slot.columns:
        actual = measure.column(wanted.name)
        if actual is None:
            problems.append(f"{wanted.name!r} is missing")
        elif actual.type != wanted.type and not (
            wanted.type is ColumnType.NUMBER and actual.type is ColumnType.INTEGER
        ):
            problems.append(f"{wanted.name!r} is {actual.type}, not {wanted.type}")
    if problems:
        raise Invalid(
            f"The alerting rows do not fit the alert pipeline's input {name!r}: "
            + "; ".join(problems)
        )
