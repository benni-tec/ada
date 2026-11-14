"""The worker and the live events: tasks queued by name onto the stream the worker reads and
run in process (in-memory broker) against fakes of the services; events broadcast only
once the unit of work that caused them committed; the server-sent event stream; and
events through Valkey pub/sub."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid7

import fastapi.routing
import pytest
from dishka import FromDishka, Provider, Scope, provide
from dishka.integrations.taskiq import inject as inject_task
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import Implementation
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from taskiq import InMemoryBroker
from taskiq_redis import RedisStreamBroker

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.valkey.events import ValkeyEventPublisher, ValkeyEventStream, channel
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
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import Alert, AlertRule
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, Unavailable
from ada.core.models.events import Event, EventType
from ada.core.models.sources import DataSource, RefreshResult
from ada.core.ports.events import EventBroadcaster, EventPublisher, EventStream
from ada.core.ports.repositories import ProjectRepository
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import make_inject
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker import create_broker
from ada.entrypoints.worker.factory import ContainerMiddleware, create_scheduler
from alerts_support import below
from api_support import call, send
from conftest import settings_in
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio

# The Valkey of `moon run root:infra`; moon sets the same value.
VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6380/0")
TASKS = "ada.entrypoints.worker.tasks"
HEARTBEAT = f"{TASKS}.system:record_heartbeat"
REFRESH_DUE_SOURCES = f"{TASKS}.sources:refresh_due_sources"
CHECK_DUE_ALERT_RULES = f"{TASKS}.alerts:check_due_alert_rules"


def event(project_id: Any, type: EventType = EventType.RUN_STARTED) -> Event:
    return Event(type=type, project_id=project_id, at=factories.NOW)


# The worker's tasks


@dataclass
class Services:
    """A fake of each service the tasks call: it records what it is asked, `due` returns
    what it is told, and `failure` makes the next call raise."""

    refreshes: list[tuple[Id, bool]] = field(default_factory=list)
    executions: list[tuple[Id, str]] = field(default_factory=list)
    checks: list[Id] = field(default_factory=list)
    due_sources: Sequence[DataSource] = ()
    due_rules: Sequence[AlertRule] = ()
    rules: dict[Id, AlertRule] = field(default_factory=dict)
    failure: Exception | None = None

    def _fail(self) -> None:
        if self.failure:
            failure, self.failure = self.failure, None
            raise failure

    async def refresh(self, id: Id, force: bool = False) -> RefreshResult:
        self.refreshes.append((id, force))
        self._fail()
        return RefreshResult(data_source_id=id, changed=True)

    async def execute(self, run_id: Id, operator_id: str) -> None:
        self.executions.append((run_id, operator_id))
        self._fail()

    async def get_rule(self, id: Id) -> AlertRule:
        return self.rules[id]

    async def check(self, rule_id: Id) -> Sequence[Alert]:
        self.checks.append(rule_id)
        self._fail()
        return []


class Sources(Services):
    async def due(self) -> Sequence[DataSource]:
        return self.due_sources


class Alerts(Services):
    async def due(self) -> Sequence[AlertRule]:
        return self.due_rules


class FlakyDispatcher(RecordingTaskDispatcher):
    """Fails to queue the first refresh and the first check it is asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.failed: list[Id] = []

    async def refresh_source(self, data_source_id: Id, force: bool = False) -> None:
        if not self.failed:
            self.failed.append(data_source_id)
            raise ConnectionError("Valkey is down")
        await super().refresh_source(data_source_id, force)

    async def check_alert_rule(self, rule_id: Id) -> None:
        if len(self.failed) == 1:
            self.failed.append(rule_id)
            raise ConnectionError("Valkey is down")
        await super().check_alert_rule(rule_id)


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
            "created_at": factories.NOW,
        }
        | changes
    )


class Fakes(Provider):
    def __init__(self, services: Services, dispatcher: TaskDispatcher) -> None:
        super().__init__(scope=Scope.APP)
        self.services = services
        self.dispatcher = dispatcher
        self.alerts = Alerts()
        self.alerts.rules = services.rules

    @provide
    def sources(self) -> SourceService:
        return self.services  # type: ignore[return-value]

    @provide
    def runs(self) -> RunService:
        return self.services  # type: ignore[return-value]

    @provide
    def alert_service(self) -> AlertService:
        return self.alerts  # type: ignore[return-value]

    @provide
    def dispatcher_(self) -> TaskDispatcher:
        return self.dispatcher


@pytest.fixture
async def worker(unreachable_settings: Settings) -> AsyncIterator[tuple[InMemoryBroker, Fakes]]:
    fakes = Fakes(Sources(), FlakyDispatcher())
    broker = create_broker(unreachable_settings, fakes, in_memory=True)
    assert isinstance(broker, InMemoryBroker)
    await broker.startup()
    yield broker, fakes
    await broker.shutdown()


async def kick(broker: InMemoryBroker, name: str, **kwargs: object) -> None:
    task = broker.find_task(name)
    assert task is not None
    result = await (await task.kiq(**kwargs)).wait_result(timeout=5)
    assert not result.is_err, result.error


def test_the_tasks_are_registered_and_the_ticks_scheduled(unreachable_settings: Settings) -> None:
    broker = create_broker(unreachable_settings, in_memory=True)

    for name in (HEARTBEAT, REFRESH_DUE_SOURCES, CHECK_DUE_ALERT_RULES):
        task = broker.find_task(name)
        assert task is not None and task.labels["schedule"] == [{"cron": "* * * * *"}], name
    # The names the dispatcher kicks are tasks the worker runs, queued on demand only.
    for name in (REFRESH_SOURCE, EXECUTE, CHECK_ALERT_RULE, RUN_TURN):
        task = broker.find_task(name)
        assert task is not None and not task.labels.get("schedule"), name
    assert create_scheduler(broker).sources
    # And the dispatcher puts them on the stream, in the group, the worker reads.
    worker = create_broker(unreachable_settings)
    dispatcher = stream_broker(unreachable_settings.valkey_url)
    assert isinstance(worker, RedisStreamBroker)
    assert (dispatcher.queue_name, dispatcher.consumer_group_name) == (
        worker.queue_name,
        worker.consumer_group_name,
    )


async def test_dispatched_tasks_run_through_the_services_with_the_arguments_given(
    worker: tuple[InMemoryBroker, Fakes],
) -> None:
    # Kicking through the worker's own broker runs the real task functions, so this checks
    # that names, argument names and argument types fit together.
    broker, fakes = worker
    dispatcher = ValkeyTaskDispatcher(broker)
    source_id, run_id = uuid7(), uuid7()
    enabled, disabled = rule(), rule(enabled=False)
    fakes.services.rules.update({enabled.id: enabled, disabled.id: disabled})

    await dispatcher.refresh_source(source_id, force=True)
    await dispatcher.execute(run_id, "op_abc")
    await dispatcher.check_alert_rule(enabled.id)
    # Disabled after it was queued: not checked.
    await dispatcher.check_alert_rule(disabled.id)
    await broker.wait_all()  # type: ignore[attr-defined]

    assert fakes.services.refreshes == [(source_id, True)]
    assert isinstance(fakes.services.refreshes[0][0], UUID)
    assert fakes.services.executions == [(run_id, "op_abc")]
    assert fakes.alerts.checks == [enabled.id]


async def test_a_failing_task_is_logged_and_the_worker_goes_on(
    worker: tuple[InMemoryBroker, Fakes], caplog: pytest.LogCaptureFixture
) -> None:
    broker, fakes = worker
    services, alerts = fakes.services, fakes.alerts
    checked = rule()
    services.rules[checked.id] = checked

    with caplog.at_level(logging.ERROR):
        services.failure = RuntimeError("the source is down")
        await kick(broker, REFRESH_SOURCE, data_source_id=str(uuid7()))
        services.failure = RuntimeError("bad SQL")
        await kick(broker, EXECUTE, run_id=str(uuid7()), operator_id="op_abc")
        alerts.failure = RuntimeError("the measure has no data")
        await kick(broker, CHECK_ALERT_RULE, rule_id=str(checked.id))
        # A rule that no longer exists is logged too.
        await kick(broker, CHECK_ALERT_RULE, rule_id=str(uuid7()))
    await kick(broker, REFRESH_SOURCE, data_source_id=str(uuid7()))

    for message in ("the source is down", "bad SQL", "the measure has no data"):
        assert message in caplog.text
    assert len(services.refreshes) == 2


async def test_the_ticks_queue_a_task_per_due_item_and_go_on_when_queueing_one_fails(
    worker: tuple[InMemoryBroker, Fakes],
) -> None:
    broker, fakes = worker
    project_id = uuid7()
    sources = [factories.data_source(project_id), factories.data_source(project_id)]
    rules = [rule(), rule()]
    fakes.services.due_sources = sources  # type: ignore[attr-defined]
    fakes.alerts.due_rules = rules
    dispatcher = fakes.dispatcher
    assert isinstance(dispatcher, FlakyDispatcher)

    await kick(broker, REFRESH_DUE_SOURCES)
    await kick(broker, CHECK_DUE_ALERT_RULES)

    assert dispatcher.failed == [sources[0].id, rules[0].id]
    assert dispatcher.refreshes == [(sources[1].id, False)]
    assert dispatcher.alert_checks == [rules[1].id]
    # Queued, not run in the tick.
    assert fakes.services.refreshes == fakes.alerts.checks == []


async def test_queueing_fails_loudly_when_valkey_is_unreachable(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings)
    try:
        assert isinstance(await container.get(TaskDispatcher), ValkeyTaskDispatcher)
    finally:
        await container.close()
    dispatcher = ValkeyTaskDispatcher(stream_broker(unreachable_settings.valkey_url))
    # Starting does not fail: the API must come up while Valkey is down.
    await dispatcher.startup()
    try:
        with pytest.raises(Unavailable, match="task queue could not be reached"):
            await dispatcher.refresh_source(uuid7())
    finally:
        await dispatcher.shutdown()


@pytest.fixture
async def valkey() -> AsyncIterator[Redis]:
    """A client of VALKEY_URL. Skipped when Valkey is not running, except in CI."""
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
        groups = await valkey.xinfo_groups(queue)
    finally:
        await dispatcher.shutdown()
        await valkey.delete(queue)

    [(_, fields)] = entries
    body = json.loads(fields[b"data"])
    assert (body["task_name"], body["kwargs"]) == (
        EXECUTE,
        {"run_id": str(run_id), "operator_id": "op_abc"},
    )
    # Starting declared the worker's consumer group, so the worker reads the message even
    # if it starts after it was queued.
    assert [group["name"] for group in groups] == [b"taskiq"]


# Events after the commit


class CheckingBroadcaster:
    """Records, for each event, whether the project it names can be read from another
    connection at the moment the event goes out."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url)
        self.seen: list[bool] = []

    async def publish(self, event: Event) -> None:
        async with self.engine.connect() as connection:
            found = await connection.execute(
                text("SELECT count(*) FROM projects WHERE id = :id"), {"id": event.project_id}
            )
            self.seen.append(found.scalar_one() == 1)


async def test_an_event_goes_out_only_after_its_data_is_committed(
    migrated_database_url: str, tmp_path: Path
) -> None:
    broadcaster = CheckingBroadcaster(migrated_database_url)
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: broadcaster, provides=EventBroadcaster)
    container = create_container(
        settings_in(tmp_path, migrated_database_url), MemoryBackground(), provider
    )
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
            await (await request.get(EventPublisher)).publish(event(project.id))
            assert broadcaster.seen == []
        assert broadcaster.seen == [True]

        other = factories.project()
        with pytest.raises(RuntimeError):
            async with container() as request:
                await (await request.get(ProjectRepository)).add(other)
                await (await request.get(EventPublisher)).publish(event(other.id))
                raise RuntimeError("the work failed")
        assert broadcaster.seen == [True]
    finally:
        await container.close()
        await broadcaster.engine.dispose()


def test_a_rest_request_answered_with_an_error_rolls_back_and_announces_nothing(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = settings_in(tmp_path, migrated_database_url)
    # The repositories of the composition root: PostgreSQL.
    with TestClient(create_app(settings, MemoryBackground())) as client:
        project = send(client, "POST", "/projects", {"name": "P"}, 201)
        send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "S"}, 201)
        source = {
            "name": "S",
            "access_kind": "url",
            "address": "https://example.test/data.csv",
            "format": "csv",
            "declared_schema": {"columns": [{"name": "region", "type": "text"}]},
        }
        send(client, "POST", f"/projects/{project['id']}/sources", source, 201)
        pipelines = f"/projects/{project['id']}/pipelines"
        [reading] = send(client, "GET", pipelines)
        # Adds the transform, then fails on the unknown session to record it in: the
        # transform must not stay.
        response = client.post(
            f"/api/projects/{project['id']}/operators",
            json={
                "kind": "transform",
                "sql": "SELECT region FROM input_0",
                "inputs": [reading["operator_id"]],
                "session_id": str(uuid7()),
            },
        )
        after = send(client, "GET", pipelines)
        container = client.app.state.dishka_container  # type: ignore[attr-defined]
        assert client.portal is not None
        bus = client.portal.call(container.get, MemoryEventBus)

    assert (response.status_code, after) == (404, [reading])
    assert response.json()["detail"].startswith("session ")
    # Only the successful requests announced anything.
    assert [e.type for e in bus.published] == [EventType.SESSION_CREATED]


async def test_a_failed_mcp_tool_or_worker_task_announces_nothing(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, *memory_adapters())
    bus = await container.get(MemoryEventBus)
    # A bare server: the platform's checks the session of every call, which is not the
    # point here (see the test after this one).
    mcp = FastMCP("test")
    broker = InMemoryBroker()
    broker.add_middlewares(ContainerMiddleware(container))

    async def announce(fail: bool, events: FromDishka[EventPublisher]) -> str:
        await events.publish(event(uuid7()))
        if fail:
            raise Invalid("the work failed")
        return "done"

    mcp.tool(make_inject(container)(announce), name="announce")
    task = broker.register_task(inject_task(announce, patch_module=True), "test:announce")
    await broker.startup()
    try:
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("announce", {"fail": True})
            await (await task.kiq(fail=True)).wait_result()
            assert bus.published == []
            await client.call_tool("announce", {"fail": False})
            await (await task.kiq(fail=False)).wait_result()
        assert len(bus.published) == 2
    finally:
        await broker.shutdown()
        await container.close()


async def test_a_tool_call_is_recorded_in_a_transaction_of_its_own_even_when_it_fails(
    migrated_database_url: str, tmp_path: Path
) -> None:
    container = create_container(settings_in(tmp_path, migrated_database_url), MemoryBackground())
    bus = await container.get(MemoryEventBus)
    mcp = create_mcp(container)

    async def add_note(
        session_id: Id, text: str, fail: bool, sessions: FromDishka[SessionService]
    ) -> str:
        await sessions.add_message(session_id, text, calling_agent())
        if fail:
            raise Invalid("the work failed")
        return "done"

    mcp.tool(make_inject(container)(add_note), name="add_note")
    try:
        info = Implementation(name="claude-code", version="1")
        async with Client(mcp, client_info=info) as client:
            project = await call(client, "create_project", name="P")
            session = await call(client, "create_session", project_id=project["id"], title="S")
            note = {"session_id": session["id"], "text": "kept", "fail": False}
            await client.call_tool("add_note", note)
            with pytest.raises(ToolError, match="the work failed"):
                await client.call_tool("add_note", {**note, "text": "lost", "fail": True})
        async with container() as request:
            entries = await (await request.get(SessionService)).entries(UUID(session["id"]))
    finally:
        await container.close()

    # The failed call's own message was rolled back; its record was committed.
    assert [(e.kind, e.text) for e in entries] == [
        ("message", "kept"),
        ("tool_call", ""),
        ("tool_call", ""),
    ]
    ok, failed = (e.tool_call for e in entries[1:])
    assert ok is not None and (ok.tool, ok.status, ok.error) == ("add_note", "ok", None)
    assert failed is not None and (failed.status, failed.error) == ("error", "the work failed")
    assert failed.arguments == {**note, "text": "lost", "fail": True}
    assert entries[2].actor == Actor(kind=ActorKind.EXTERNAL_AGENT, name="claude-code")
    # Each entry announced after its commit, and nothing else.
    added = [
        e.payload["entry_id"] for e in bus.published if e.type is EventType.SESSION_ENTRY_ADDED
    ]
    assert added == [str(e.id) for e in entries]


# The server-sent event stream. The test client waits for the whole body, which an event
# stream never finishes, so these tests speak ASGI to the app directly.


@dataclass
class Connection:
    """One request to the app, with a client that can hang up."""

    task: asyncio.Task[None]
    sent: asyncio.Queue[dict[str, Any]]
    hang_up: asyncio.Event
    headers: dict[str, str] = field(default_factory=dict)

    async def next_chunk(self) -> bytes:
        message = await asyncio.wait_for(self.sent.get(), 5)
        assert message["type"] == "http.response.body"
        return message["body"]

    async def close(self) -> None:
        self.hang_up.set()
        await asyncio.wait_for(self.task, 5)


async def connect(app: FastAPI, path: str) -> Connection:
    sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    hang_up = asyncio.Event()
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await hang_up.wait()
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        # What uvicorn reports: the server tells the app when the client disconnects.
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test"), (b"accept", b"text/event-stream")],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    connection = Connection(asyncio.create_task(app(scope, receive, sent.put)), sent, hang_up)
    start = await asyncio.wait_for(sent.get(), 5)
    assert (start["type"], start["status"]) == ("http.response.start", 200)
    connection.headers = {name.decode(): value.decode() for name, value in start["headers"]}
    return connection


class MemoryEvents(Provider):
    def __init__(self, bus: MemoryEventBus) -> None:
        super().__init__(scope=Scope.APP)
        self.bus = bus

    @provide
    def stream(self) -> EventStream:
        return self.bus


async def until_subscribed(bus: MemoryEventBus, project_id: UUID, count: int = 1) -> None:
    async with asyncio.timeout(5):
        # Polled: the subscription is someone else's state, with nothing to wait on.
        while True:
            if len(bus._subscribers.get(project_id, ())) == count:
                return
            await asyncio.sleep(0.01)


@pytest.fixture(scope="module")
def bus() -> MemoryEventBus:
    return MemoryEventBus()


@pytest.fixture(scope="module")
def app(unreachable_settings: Settings, bus: MemoryEventBus) -> FastAPI:
    return create_app(unreachable_settings, *memory_adapters(), MemoryEvents(bus))


async def test_the_stream_sends_the_projects_events_unbuffered_and_ends_with_the_client(
    app: FastAPI, bus: MemoryEventBus
) -> None:
    project_id = uuid7()
    stream = await connect(app, f"/api/projects/{project_id}/events")
    await until_subscribed(bus, project_id)
    sent = Event(
        type=EventType.SESSION_ENTRY_ADDED,
        project_id=project_id,
        payload={"session_id": str(uuid7()), "entry_id": str(uuid7())},
        at=factories.NOW,
    )
    # Another project's event is not sent.
    await bus.publish(event(uuid7()))
    await bus.publish(sent)
    chunk = (await stream.next_chunk()).decode()

    await stream.close()

    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    # nginx would otherwise hold events back until its buffer fills.
    assert stream.headers["x-accel-buffering"] == "no"
    event_line, data_line = chunk.removesuffix("\n\n").split("\n")
    assert event_line == "event: session.entry_added"
    assert Event.model_validate_json(data_line.removeprefix("data: ")) == sent
    # The request finished instead of waiting for the next event, and unsubscribed.
    await until_subscribed(bus, project_id, count=0)


async def test_a_quiet_stream_sends_comments_to_stay_open(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FastAPI sends the keep-alive; the contract's interval is its default.
    assert fastapi.routing._PING_INTERVAL == 15
    monkeypatch.setattr(fastapi.routing, "_PING_INTERVAL", 0.05)
    connection = await connect(app, f"/api/projects/{uuid7()}/events")
    try:
        chunk = await connection.next_chunk()
    finally:
        await connection.close()
    # A line starting with a colon is a comment; EventSource ignores it.
    assert chunk.startswith(b":") and chunk.endswith(b"\n\n")


# Valkey pub/sub. Every test uses a project id of its own, so its channel is its own too.


async def subscribers(valkey: Redis, project_id: Id) -> int:
    [(_, count)] = await valkey.pubsub_numsub(channel(project_id))
    return count


async def until_valkey_subscribed(valkey: Redis, project_id: Id, count: int = 1) -> None:
    """Pub/sub keeps nothing, so a test publishes only once the subscription is live."""
    async with asyncio.timeout(5):
        while True:
            if await subscribers(valkey, project_id) == count:
                return
            await asyncio.sleep(0.01)


async def stop(received: asyncio.Future[Event], events: AsyncGenerator[Event]) -> None:
    """End a subscription whose next event a test was waiting for."""
    received.cancel()
    # The generator cannot be closed while the waiting task is still inside it.
    await asyncio.gather(received, return_exceptions=True)
    await events.aclose()


async def test_an_event_reaches_the_projects_subscribers_in_another_container(
    valkey: Redis, tmp_path: Path
) -> None:
    # The worker and the API each build their own container; Valkey connects them.
    settings = Settings(
        database_url="postgresql+psycopg://test@127.0.0.1:1/test",
        valkey_url=VALKEY_URL,
        data_dir=tmp_path,
    )
    worker, api = create_container(settings), create_container(settings)
    project_id = uuid7()
    try:
        events = (await api.get(EventStream)).subscribe(project_id)
        received = asyncio.ensure_future(anext(events))
        try:
            await until_valkey_subscribed(valkey, project_id)
            # A message that is no event is skipped, another project's goes elsewhere.
            await valkey.publish(channel(project_id), "not an event")
            await (await worker.get(EventBroadcaster)).publish(event(uuid7()))
            sent = event(project_id, EventType.SOURCE_REFRESHED)
            await (await worker.get(EventBroadcaster)).publish(sent)
            assert await asyncio.wait_for(received, 5) == sent
        finally:
            await stop(received, events)
        # Stopping the iteration ends the subscription.
        await until_valkey_subscribed(valkey, project_id, count=0)
    finally:
        await worker.close()
        await api.close()


async def test_publishing_does_not_raise_when_valkey_is_unreachable(
    unreachable_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    container = create_container(unreachable_settings)
    try:
        publisher = await container.get(EventBroadcaster)
        assert isinstance(publisher, ValkeyEventPublisher)
        with caplog.at_level(logging.WARNING):
            await publisher.publish(event(uuid7(), EventType.RUN_FINISHED))
        assert "Dropped run.finished event" in caplog.text
    finally:
        await container.close()


async def test_cancelling_a_subscriber_ends_its_subscription(valkey: Redis) -> None:
    # What happens when a client of the event stream disconnects.
    project_id = uuid7()

    async def consume() -> None:
        async for _ in ValkeyEventStream(valkey).subscribe(project_id):
            pass

    consumer = asyncio.create_task(consume())
    await until_valkey_subscribed(valkey, project_id)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    await until_valkey_subscribed(valkey, project_id, count=0)
