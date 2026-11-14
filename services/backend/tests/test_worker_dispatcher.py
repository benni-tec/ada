"""Queueing tasks for the worker: the dispatcher kicks the worker's tasks by name, with
arguments the tasks accept, onto the stream the worker reads."""

import importlib.util
import json
import os
from collections.abc import AsyncGenerator, AsyncIterator
from uuid import uuid4, uuid7

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from taskiq import AsyncBroker, BrokerMessage
from taskiq_redis import RedisStreamBroker

from ada.adapters.valkey.tasks import (
    CHECK_ALERT_RULE,
    EXECUTE,
    REFRESH_SOURCE,
    RUN_TURN,
    ValkeyTaskDispatcher,
    stream_broker,
)
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Unavailable
from ada.core.ports.tasks import TaskDispatcher
from ada.entrypoints.worker import create_broker
from test_worker_tasks import FakeRunService, FakeSourceService, fakes

pytestmark = pytest.mark.anyio

# The Valkey of `moon run root:infra`; moon sets the same value.
VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6380/0")


class RecordingBroker(AsyncBroker):
    """Keeps what is kicked instead of sending it."""

    def __init__(self) -> None:
        super().__init__()
        self.kicked: list[BrokerMessage] = []

    async def kick(self, message: BrokerMessage) -> None:
        self.kicked.append(message)

    async def listen(self) -> AsyncGenerator[bytes]:
        raise NotImplementedError
        yield b""

    def sent(self) -> list[tuple[str, list[object], dict[str, object]]]:
        """Task name, positional and keyword arguments of each message, as the worker reads
        them."""
        decoded = [json.loads(message.message) for message in self.kicked]
        return [(body["task_name"], body["args"], body["kwargs"]) for body in decoded]


async def test_the_dispatcher_kicks_each_task_by_name_with_its_arguments() -> None:
    broker = RecordingBroker()
    dispatcher = ValkeyTaskDispatcher(broker)
    source_id, run_id, rule_id, turn_id = uuid7(), uuid7(), uuid7(), uuid7()

    await dispatcher.refresh_source(source_id)
    await dispatcher.refresh_source(source_id, force=True)
    await dispatcher.execute(run_id, "op_abc")
    await dispatcher.check_alert_rule(rule_id)
    await dispatcher.run_turn(turn_id)

    assert broker.sent() == [
        (REFRESH_SOURCE, [], {"data_source_id": str(source_id), "force": False}),
        (REFRESH_SOURCE, [], {"data_source_id": str(source_id), "force": True}),
        (EXECUTE, [], {"run_id": str(run_id), "operator_id": "op_abc"}),
        (CHECK_ALERT_RULE, [], {"rule_id": str(rule_id)}),
        (RUN_TURN, [], {"turn_id": str(turn_id)}),
    ]


@pytest.mark.parametrize("name", [REFRESH_SOURCE, EXECUTE, CHECK_ALERT_RULE, RUN_TURN])
def test_the_names_kicked_are_the_tasks_the_worker_registers(
    unreachable_settings: Settings, name: str
) -> None:
    module = name.split(":")[0]
    if importlib.util.find_spec(module) is None:
        # check_alert_rule comes with the alerts of wave 2.
        pytest.skip(f"{module} does not exist yet")
    assert create_broker(unreachable_settings, in_memory=True).find_task(name) is not None


def test_the_dispatcher_uses_the_stream_and_group_the_worker_reads(
    unreachable_settings: Settings,
) -> None:
    worker = create_broker(unreachable_settings)
    dispatcher = stream_broker(unreachable_settings.valkey_url)
    assert isinstance(worker, RedisStreamBroker)
    assert dispatcher.queue_name == worker.queue_name
    assert dispatcher.consumer_group_name == worker.consumer_group_name


async def test_dispatched_tasks_run_with_the_arguments_they_were_given(
    unreachable_settings: Settings,
) -> None:
    # Kicking through the worker's own in-memory broker runs the real task functions, so
    # this checks that names, argument names and argument types fit together.
    sources, runs = FakeSourceService(), FakeRunService()
    broker = create_broker(unreachable_settings, fakes(sources=sources, runs=runs), in_memory=True)
    await broker.startup()
    try:
        dispatcher = ValkeyTaskDispatcher(broker)
        source_id, run_id = uuid7(), uuid7()
        await dispatcher.refresh_source(source_id, force=True)
        await dispatcher.execute(run_id, "op_abc")
        await broker.wait_all()  # type: ignore[attr-defined]
    finally:
        await broker.shutdown()
    assert sources.refreshes == [(source_id, True)]
    assert runs.executions == [(run_id, "op_abc")]


async def test_queueing_fails_loudly_when_valkey_is_unreachable(
    unreachable_settings: Settings,
) -> None:
    dispatcher = ValkeyTaskDispatcher(stream_broker(unreachable_settings.valkey_url))
    # Starting does not fail: the API must come up while Valkey is down.
    await dispatcher.startup()
    try:
        with pytest.raises(Unavailable, match="task queue could not be reached"):
            await dispatcher.refresh_source(uuid7())
    finally:
        await dispatcher.shutdown()


async def test_the_container_binds_the_valkey_dispatcher(unreachable_settings: Settings) -> None:
    container = create_container(unreachable_settings)
    try:
        assert isinstance(await container.get(TaskDispatcher), ValkeyTaskDispatcher)
    finally:
        await container.close()


@pytest.fixture
async def valkey() -> AsyncIterator[Redis]:
    """A client of VALKEY_URL. Skipped when it is not running, except in CI."""
    client = Redis.from_url(VALKEY_URL, socket_connect_timeout=2)
    try:
        await client.ping()
    except (RedisError, OSError) as error:
        await client.aclose()
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Valkey is not reachable: {error}")
    yield client
    await client.aclose()


async def test_a_kicked_task_lands_on_the_stream(valkey: Redis) -> None:
    # A stream of its own, so neither a running worker nor another test sees the message.
    queue = f"ada:test:tasks:{uuid4().hex}"
    dispatcher = ValkeyTaskDispatcher(RedisStreamBroker(VALKEY_URL, queue_name=queue))
    await dispatcher.startup()
    try:
        run_id = uuid7()
        await dispatcher.execute(run_id, "op_abc")

        entries = await valkey.xrange(queue)
        assert len(entries) == 1
        body = json.loads(entries[0][1][b"data"])
        assert body["task_name"] == EXECUTE
        assert body["kwargs"] == {"run_id": str(run_id), "operator_id": "op_abc"}
        # Starting declared the worker's consumer group, so the worker reads the message
        # even if it starts after it was queued.
        groups = await valkey.xinfo_groups(queue)
        assert [group["name"] for group in groups] == [b"taskiq"]
    finally:
        await dispatcher.shutdown()
        await valkey.delete(queue)
