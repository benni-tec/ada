"""The alert tasks of the worker, run in process (in-memory broker): against a fake of the
alert service, and once end to end against the real services and DuckDB."""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import Provider, Scope
from taskiq import AsyncBroker, InMemoryBroker

from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.valkey.tasks import ValkeyTaskDispatcher
from ada.config import Settings
from ada.core.models.alerts import Alert, AlertRule, AlertState
from ada.core.models.base import Id
from ada.core.models.events import EventType
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.entrypoints.worker import create_broker
from ada.entrypoints.worker.factory import ContainerMiddleware
from alerts_support import AlertOverrides, World, below, csv
from factories import NOW
from memory import memory_adapters

pytestmark = pytest.mark.anyio

CHECK_ALERT_RULE = "ada.entrypoints.worker.tasks.alerts:check_alert_rule"
CHECK_DUE_ALERT_RULES = "ada.entrypoints.worker.tasks.alerts:check_due_alert_rules"


def rule(**changes: Any) -> AlertRule:
    return AlertRule(
        **{
            "id": uuid7(),
            "project_id": uuid7(),
            "dashboard_id": uuid7(),
            "name": "Low",
            "operator_id": "op_measure",
            "formula": below(80),
            "key_columns": ("region",),
            "created_at": NOW,
        }
        | changes
    )


class FakeAlertService:
    """Records checks; `due` returns what it is told; `failure` makes check raise."""

    def __init__(self) -> None:
        self.rules: dict[Id, AlertRule] = {}
        self.checks: list[Id] = []
        self.due_rules: Sequence[AlertRule] = ()
        self.failure: Exception | None = None

    async def get_rule(self, id: Id) -> AlertRule:
        return self.rules[id]

    async def check(self, rule_id: Id) -> Sequence[Alert]:
        self.checks.append(rule_id)
        if self.failure:
            raise self.failure
        return []

    async def due(self) -> Sequence[AlertRule]:
        return self.due_rules


def fakes(service: FakeAlertService, dispatcher: TaskDispatcher) -> Provider:
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: service, provides=AlertService)
    provider.provide(lambda: dispatcher, provides=TaskDispatcher)
    return provider


async def run(broker: AsyncBroker, name: str, **kwargs: object) -> None:
    task = broker.find_task(name)
    assert task is not None
    result = await (await task.kiq(**kwargs)).wait_result(timeout=5)
    assert not result.is_err, result.error


@pytest.fixture
def service() -> FakeAlertService:
    return FakeAlertService()


@pytest.fixture
def dispatcher() -> RecordingTaskDispatcher:
    return RecordingTaskDispatcher()


@pytest.fixture
async def broker(
    unreachable_settings: Settings, service: FakeAlertService, dispatcher: RecordingTaskDispatcher
) -> AsyncIterator[InMemoryBroker]:
    broker = create_broker(unreachable_settings, fakes(service, dispatcher), in_memory=True)
    assert isinstance(broker, InMemoryBroker)
    await broker.startup()
    yield broker
    await broker.shutdown()


def test_the_tasks_are_registered_with_their_schedules(unreachable_settings: Settings) -> None:
    broker = create_broker(unreachable_settings, in_memory=True)
    due = broker.find_task(CHECK_DUE_ALERT_RULES)
    assert due is not None
    assert due.labels["schedule"] == [{"cron": "* * * * *"}]
    check = broker.find_task(CHECK_ALERT_RULE)
    assert check is not None
    assert not check.labels.get("schedule")


async def test_check_alert_rule_checks_through_the_service(
    broker: InMemoryBroker, service: FakeAlertService
) -> None:
    enabled = rule()
    service.rules[enabled.id] = enabled
    await run(broker, CHECK_ALERT_RULE, rule_id=str(enabled.id))
    assert service.checks == [enabled.id]
    assert isinstance(service.checks[0], UUID)


async def test_a_rule_disabled_after_it_was_queued_is_not_checked(
    broker: InMemoryBroker, service: FakeAlertService
) -> None:
    disabled = rule(enabled=False)
    service.rules[disabled.id] = disabled
    await run(broker, CHECK_ALERT_RULE, rule_id=str(disabled.id))
    assert service.checks == []


async def test_a_failing_check_is_logged_and_the_worker_goes_on(
    broker: InMemoryBroker, service: FakeAlertService, caplog: pytest.LogCaptureFixture
) -> None:
    first, second = rule(), rule()
    service.rules = {first.id: first, second.id: second}
    service.failure = RuntimeError("the measure has no data")
    with caplog.at_level(logging.ERROR):
        await run(broker, CHECK_ALERT_RULE, rule_id=str(first.id))
    assert "the measure has no data" in caplog.text
    service.failure = None
    await run(broker, CHECK_ALERT_RULE, rule_id=str(second.id))
    assert service.checks == [first.id, second.id]
    # A rule that no longer exists is logged too.
    with caplog.at_level(logging.ERROR):
        await run(broker, CHECK_ALERT_RULE, rule_id=str(uuid7()))


async def test_check_due_alert_rules_queues_a_check_per_due_rule(
    broker: InMemoryBroker, service: FakeAlertService, dispatcher: RecordingTaskDispatcher
) -> None:
    service.due_rules = [rule(), rule()]
    await run(broker, CHECK_DUE_ALERT_RULES)
    assert dispatcher.alert_checks == [r.id for r in service.due_rules]
    # Queued, not run in the tick.
    assert service.checks == []


class FlakyDispatcher(RecordingTaskDispatcher):
    """Fails to queue the first check it is asked for."""

    async def check_alert_rule(self, rule_id: Id) -> None:
        if not hasattr(self, "failed"):
            self.failed = rule_id
            raise ConnectionError("Valkey is down")
        await super().check_alert_rule(rule_id)


async def test_check_due_alert_rules_goes_on_when_queueing_one_fails(
    unreachable_settings: Settings, service: FakeAlertService
) -> None:
    service.due_rules = [rule(), rule()]
    dispatcher = FlakyDispatcher()
    broker = create_broker(unreachable_settings, fakes(service, dispatcher), in_memory=True)
    await broker.startup()
    try:
        await run(broker, CHECK_DUE_ALERT_RULES)
    finally:
        await broker.shutdown()
    assert dispatcher.failed == service.due_rules[0].id
    assert dispatcher.alert_checks == [service.due_rules[1].id]


async def test_due_rules_are_checked_end_to_end(unreachable_settings: Settings) -> None:
    """The scheduled tick queues through the dispatcher the API uses, and the queued task
    checks the rule with the real services and announces the alert."""
    overrides = AlertOverrides()
    # A dispatcher that kicks the worker's own in-memory broker, bound before the broker
    # exists: the provider asks for it when a task first needs it.
    holder: dict[str, AsyncBroker] = {}
    background = Provider(scope=Scope.APP)
    background.provide(lambda: ValkeyTaskDispatcher(holder["broker"]), provides=TaskDispatcher)
    events_and_repositories = memory_adapters()
    broker = create_broker(
        unreachable_settings, *events_and_repositories, overrides, background, in_memory=True
    )
    holder["broker"] = broker
    await broker.startup()
    try:
        container = next(
            m for m in broker.middlewares if isinstance(m, ContainerMiddleware)
        )._container
        world = World(container, overrides)
        setup = await world.setup(csv(("north", 2024, 70), ("south", 2024, 90)))
        created = await world.rule(setup)
        await run(broker, CHECK_DUE_ALERT_RULES)
        await broker.wait_all()  # type: ignore[attr-defined]
        async with world.alerts() as alerts:
            (alert,) = await alerts.alerts(setup.project_id, AlertState.FIRING)
            assert (await alerts.get_rule(created.id)).last_checked_at == world.clock.now()
        assert alert.key == {"region": "north"}
        assert EventType.ALERT_FIRING in [event.type for event in await world.events()]
    finally:
        await broker.shutdown()
