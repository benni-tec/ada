"""The worker's tasks, run in process (in-memory broker) against small fakes of the
services they call."""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import Provider, Scope
from taskiq import AsyncBroker, InMemoryBroker

import factories
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.config import Settings
from ada.core.models.base import Id
from ada.core.models.sources import DataSource, RefreshResult
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.worker import create_broker

pytestmark = pytest.mark.anyio

REFRESH_SOURCE = "ada.entrypoints.worker.tasks.sources:refresh_source"
REFRESH_DUE_SOURCES = "ada.entrypoints.worker.tasks.sources:refresh_due_sources"
EXECUTE = "ada.entrypoints.worker.tasks.runs:execute"


class FakeSourceService:
    """Records refreshes; `due` returns what it is told; `failure` makes refresh raise."""

    def __init__(self, due: Sequence[DataSource] = ()) -> None:
        self.refreshes: list[tuple[Id, bool]] = []
        self.due_sources = due
        self.failure: Exception | None = None

    async def refresh(self, id: Id, force: bool = False) -> RefreshResult:
        self.refreshes.append((id, force))
        if self.failure:
            raise self.failure
        return RefreshResult(data_source_id=id, changed=True)

    async def due(self) -> Sequence[DataSource]:
        return self.due_sources


class FakeRunService:
    def __init__(self) -> None:
        self.executions: list[tuple[Id, str]] = []
        self.failure: Exception | None = None

    async def execute(self, run_id: Id, operator_id: str) -> None:
        self.executions.append((run_id, operator_id))
        if self.failure:
            raise self.failure


def fakes(**bindings: Any) -> Provider:
    """A provider binding each port (by type) to the given instance."""
    provider = Provider(scope=Scope.APP)
    for port, instance in bindings.items():
        provider.provide(constant(instance), provides=PORTS[port])
    return provider


def constant(instance: object) -> Any:
    def factory() -> Any:
        return instance

    return factory


PORTS: dict[str, type] = {
    "sources": SourceService,
    "runs": RunService,
    "dispatcher": TaskDispatcher,
}


async def run(broker: AsyncBroker, name: str, **kwargs: object) -> None:
    task = broker.find_task(name)
    assert task is not None
    result = await (await task.kiq(**kwargs)).wait_result(timeout=5)
    assert not result.is_err, result.error


@pytest.fixture
def sources() -> FakeSourceService:
    return FakeSourceService()


@pytest.fixture
def runs() -> FakeRunService:
    return FakeRunService()


@pytest.fixture
def dispatcher() -> RecordingTaskDispatcher:
    return RecordingTaskDispatcher()


@pytest.fixture
async def broker(
    unreachable_settings: Settings,
    sources: FakeSourceService,
    runs: FakeRunService,
    dispatcher: RecordingTaskDispatcher,
) -> AsyncIterator[InMemoryBroker]:
    broker = create_broker(
        unreachable_settings,
        fakes(sources=sources, runs=runs, dispatcher=dispatcher),
        in_memory=True,
    )
    assert isinstance(broker, InMemoryBroker)
    await broker.startup()
    yield broker
    await broker.shutdown()


def test_tasks_are_registered_with_their_schedules(unreachable_settings: Settings) -> None:
    broker = create_broker(unreachable_settings, in_memory=True)
    due = broker.find_task(REFRESH_DUE_SOURCES)
    assert due is not None
    assert due.labels["schedule"] == [{"cron": "* * * * *"}]
    for name in (REFRESH_SOURCE, EXECUTE):
        task = broker.find_task(name)
        assert task is not None
        # Queued on demand only.
        assert not task.labels.get("schedule")


async def test_refresh_source_refreshes_through_the_service(
    broker: InMemoryBroker, sources: FakeSourceService
) -> None:
    source_id = uuid7()
    await run(broker, REFRESH_SOURCE, data_source_id=str(source_id), force=True)
    await run(broker, REFRESH_SOURCE, data_source_id=str(source_id))
    assert sources.refreshes == [(source_id, True), (source_id, False)]
    assert all(isinstance(id, UUID) for id, _ in sources.refreshes)


async def test_a_failing_refresh_is_logged_and_the_worker_goes_on(
    broker: InMemoryBroker, sources: FakeSourceService, caplog: pytest.LogCaptureFixture
) -> None:
    sources.failure = RuntimeError("the source is down")
    with caplog.at_level(logging.ERROR):
        await run(broker, REFRESH_SOURCE, data_source_id=str(uuid7()))
    assert "the source is down" in caplog.text

    sources.failure = None
    await run(broker, REFRESH_SOURCE, data_source_id=str(uuid7()))
    assert len(sources.refreshes) == 2


async def test_execute_executes_through_the_run_service(
    broker: InMemoryBroker, runs: FakeRunService
) -> None:
    run_id = uuid7()
    await run(broker, EXECUTE, run_id=str(run_id), operator_id="op_abc")
    assert runs.executions == [(run_id, "op_abc")]


async def test_a_failing_execution_is_logged_and_the_worker_goes_on(
    broker: InMemoryBroker, runs: FakeRunService, caplog: pytest.LogCaptureFixture
) -> None:
    runs.failure = RuntimeError("bad SQL")
    with caplog.at_level(logging.ERROR):
        await run(broker, EXECUTE, run_id=str(uuid7()), operator_id="op_abc")
    assert "bad SQL" in caplog.text

    runs.failure = None
    await run(broker, EXECUTE, run_id=str(uuid7()), operator_id="op_def")
    assert len(runs.executions) == 2


async def test_refresh_due_sources_queues_a_refresh_per_due_source(
    broker: InMemoryBroker, sources: FakeSourceService, dispatcher: RecordingTaskDispatcher
) -> None:
    project_id = uuid7()
    due = [factories.data_source(project_id), factories.data_source(project_id)]
    sources.due_sources = due
    await run(broker, REFRESH_DUE_SOURCES)
    assert dispatcher.refreshes == [(due[0].id, False), (due[1].id, False)]
    # Queued, not run in the tick.
    assert sources.refreshes == []


class FlakyDispatcher(RecordingTaskDispatcher):
    """Fails to queue the first refresh it is asked for."""

    async def refresh_source(self, data_source_id: Id, force: bool = False) -> None:
        if not hasattr(self, "failed"):
            self.failed = data_source_id
            raise ConnectionError("Valkey is down")
        await super().refresh_source(data_source_id, force)


async def test_refresh_due_sources_goes_on_when_queueing_one_fails(
    unreachable_settings: Settings, sources: FakeSourceService, runs: FakeRunService
) -> None:
    project_id = uuid7()
    due = [factories.data_source(project_id), factories.data_source(project_id)]
    sources.due_sources = due
    dispatcher = FlakyDispatcher()
    broker = create_broker(
        unreachable_settings,
        fakes(sources=sources, runs=runs, dispatcher=dispatcher),
        in_memory=True,
    )
    await broker.startup()
    try:
        await run(broker, REFRESH_DUE_SOURCES)
    finally:
        await broker.shutdown()
    assert dispatcher.failed == due[0].id
    assert dispatcher.refreshes == [(due[1].id, False)]
