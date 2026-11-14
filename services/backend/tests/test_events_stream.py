"""The server-sent event endpoint, fed by the in-memory event bus.

The test client and httpx's ASGI transport both wait for the whole response body, which an
event stream never finishes, so these tests speak ASGI to the app directly."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid7

import fastapi.routing
import pytest
from dishka import Provider, Scope, provide
from fastapi import FastAPI

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.config import Settings
from ada.core.models.events import Event, EventType
from ada.core.ports.events import EventStream
from ada.entrypoints.http.app import create_app

pytestmark = pytest.mark.anyio


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

    async def send(message: dict[str, Any]) -> None:
        await sent.put(message)

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
    connection = Connection(asyncio.create_task(app(scope, receive, send)), sent, hang_up)
    start = await asyncio.wait_for(sent.get(), 5)
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    connection.headers = {name.decode(): value.decode() for name, value in start["headers"]}
    return connection


class MemoryEvents(Provider):
    def __init__(self, bus: MemoryEventBus) -> None:
        super().__init__(scope=Scope.APP)
        self.bus = bus

    @provide
    def stream(self) -> EventStream:
        return self.bus


@pytest.fixture
def bus() -> MemoryEventBus:
    return MemoryEventBus()


@pytest.fixture
def app(unreachable_settings: Settings, bus: MemoryEventBus) -> FastAPI:
    return create_app(unreachable_settings, MemoryEvents(bus))


async def until_subscribed(bus: MemoryEventBus, project_id: UUID, count: int = 1) -> None:
    async with asyncio.timeout(5):
        # Polled: the subscription is someone else's state, with nothing to wait on.
        while True:
            if len(bus._subscribers.get(project_id, ())) == count:
                return
            await asyncio.sleep(0.01)


@pytest.fixture
def project_id() -> UUID:
    return uuid7()


@pytest.fixture
async def stream(app: FastAPI, project_id: UUID) -> AsyncIterator[Connection]:
    connection = await connect(app, f"/api/projects/{project_id}/events")
    yield connection
    connection.hang_up.set()
    await asyncio.wait_for(connection.task, 5)


async def test_the_stream_is_unbuffered_server_sent_events(stream: Connection) -> None:
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    # nginx would otherwise hold events back until its buffer fills.
    assert stream.headers["x-accel-buffering"] == "no"


async def test_each_event_is_sent_with_its_type_and_json(
    stream: Connection, bus: MemoryEventBus, project_id: UUID
) -> None:
    await until_subscribed(bus, project_id)
    sent = Event(
        type=EventType.SESSION_ENTRY_ADDED,
        project_id=project_id,
        payload={"session_id": str(uuid7()), "entry_id": str(uuid7())},
        at=factories.NOW,
    )
    await bus.publish(sent)

    chunk = (await stream.next_chunk()).decode()
    assert chunk.endswith("\n\n")
    event_line, data_line = chunk.removesuffix("\n\n").split("\n")
    assert event_line == "event: session.entry_added"
    assert data_line.startswith("data: ")
    data = data_line.removeprefix("data: ")
    assert Event.model_validate_json(data) == sent
    assert json.loads(data)["payload"] == sent.payload


async def test_only_the_projects_events_are_sent(
    stream: Connection, bus: MemoryEventBus, project_id: UUID
) -> None:
    await until_subscribed(bus, project_id)
    for target in (uuid7(), project_id):
        await bus.publish(Event(type=EventType.WIDGET_CREATED, project_id=target, at=factories.NOW))
    data = (await stream.next_chunk()).decode().split("data: ")[1]
    assert Event.model_validate_json(data).project_id == project_id


async def test_a_quiet_stream_sends_comments_to_stay_open(
    app: FastAPI, project_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FastAPI sends the keep-alive; the contract's interval is its default.
    assert fastapi.routing._PING_INTERVAL == 15
    monkeypatch.setattr(fastapi.routing, "_PING_INTERVAL", 0.05)
    connection = await connect(app, f"/api/projects/{project_id}/events")
    try:
        for _ in range(2):
            chunk = await connection.next_chunk()
            # A line starting with a colon is a comment; EventSource ignores it.
            assert chunk.startswith(b":")
            assert chunk.endswith(b"\n\n")
    finally:
        connection.hang_up.set()
        await asyncio.wait_for(connection.task, 5)


async def test_the_stream_ends_when_the_client_disconnects(
    app: FastAPI, bus: MemoryEventBus, project_id: UUID
) -> None:
    connection = await connect(app, f"/api/projects/{project_id}/events")
    await until_subscribed(bus, project_id)

    connection.hang_up.set()
    # The request finishes instead of waiting for the next event...
    await asyncio.wait_for(connection.task, 5)
    # ...and its subscription is gone.
    await until_subscribed(bus, project_id, count=0)
