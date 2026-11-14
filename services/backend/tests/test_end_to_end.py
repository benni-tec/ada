"""The wave 1 slice, driven the way an external agent drives it: over MCP.

Everything is real except the outside world: PostgreSQL (migrated), the DuckDB store on
Parquet files in tmp_path, the HTTP source readers (answering from the recorded NORDCAN
response), and the worker's tasks, which run in an in-memory taskiq broker with their own
container, as a worker process would. Valkey is replaced by the in-memory bus, through a
broadcaster that checks, for every event, that what it names is already committed.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client
from mcp.types import Implementation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from taskiq import InMemoryBroker

from ada.adapters.clock import SystemClock
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.sources.examples import NORDCAN_LUNG_SURVIVAL
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.adapters.valkey.tasks import ValkeyTaskDispatcher
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.events import Event, EventType
from ada.core.ports.events import EventBroadcaster
from ada.core.ports.sources import SourceReaders
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker import create_broker
from memory import MemoryBackground
from test_sources_examples import Replay

pytestmark = pytest.mark.anyio

AGENT = "e2e-agent"

# Which table holds the record each payload id names.
COMMITTED = {
    "session_id": "sessions",
    "entry_id": "session_entries",
    "widget_id": "widgets",
    "run_id": "runs",
    "data_source_id": "data_sources",
}


class CommittedBroadcaster:
    """Records every broadcast event, and whether each id in its payload could be read
    from another connection at that moment, i.e. had been committed."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.bus = MemoryEventBus()
        self.unseen: list[tuple[str, str]] = []

    async def publish(self, event: Event) -> None:
        async with self.engine.connect() as connection:
            for key, table in COMMITTED.items():
                if key in event.payload:
                    found = await connection.execute(
                        text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                        {"id": UUID(str(event.payload[key]))},
                    )
                    if found.scalar_one() != 1:
                        self.unseen.append((event.type.value, key))
        await self.bus.publish(event)

    @property
    def types(self) -> list[EventType]:
        return [event.type for event in self.bus.published]


@dataclass
class Stack:
    mcp: Client
    api: AsyncContainer
    broker: InMemoryBroker
    events: CommittedBroadcaster
    replay: Replay

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self.mcp.call_tool(tool, arguments)
        content = result.structured_content
        assert content is not None
        return content["result"] if set(content) == {"result"} else content


@pytest.fixture
async def stack(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[Stack]:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    engine = create_async_engine(migrated_database_url)
    events = CommittedBroadcaster(engine)
    replay = Replay()
    readers = HttpSourceReaders(create_client(httpx.MockTransport(replay)), SystemClock())

    outside = Provider(scope=Scope.APP)
    outside.provide(lambda: events, provides=EventBroadcaster)
    outside.provide(lambda: readers, provides=SourceReaders)

    # The worker: its own container, as in its own process.
    broker = create_broker(settings, MemoryBackground(), outside, in_memory=True)
    assert isinstance(broker, InMemoryBroker)
    await broker.startup()
    # The API side queues onto that broker by task name, as it queues onto Valkey.
    queue = Provider(scope=Scope.APP)
    queue.provide(lambda: ValkeyTaskDispatcher(broker), provides=TaskDispatcher)
    api = create_container(settings, FastapiProvider(), MemoryBackground(), outside, queue)
    info = Implementation(name=AGENT, version="1.0")
    try:
        async with Client(create_mcp(api, settings.widgets_dir), client_info=info) as mcp:
            yield Stack(mcp, api, broker, events, replay)
    finally:
        await api.close()
        await broker.shutdown()
        await engine.dispose()


async def test_an_agent_builds_a_widget_from_a_public_source(stack: Stack) -> None:
    project = await stack.call("create_project", name="Nordic cancer care")
    source = await stack.call(
        "register_source",
        project_id=project["id"],
        **NORDCAN_LUNG_SURVIVAL.model_dump(mode="json"),
    )
    session = await stack.call(
        "create_session", project_id=project["id"], title="Lung cancer survival"
    )

    # Refreshing is queued; the worker fetches the source and stores its snapshot.
    queued = await stack.call("refresh_source", source_id=source["id"])
    assert queued["status"] == "queued"
    await stack.broker.wait_all()
    [refreshed] = await stack.call("list_sources", project_id=project["id"])
    assert refreshed["last_error"] is None
    assert refreshed["last_checked_at"] is not None
    assert [request.url.host for request in stack.replay.requests] == ["canapi.iarc.who.int"]

    source_operator = await stack.call(
        "add_source_operator",
        project_id=project["id"],
        data_source_id=source["id"],
        session_id=session["id"],
        note="Survival by country, sex and period",
    )
    finland = await stack.call(
        "add_transform",
        project_id=project["id"],
        sql=(
            "SELECT sex, survival, survival_lower, survival_upper FROM input_0 "
            "WHERE country = 'Finland' AND period = '2020-2024' ORDER BY sex"
        ),
        inputs=[source_operator["id"]],
        session_id=session["id"],
        note="Finland, latest period",
    )
    assert [column["name"] for column in finland["output"]["columns"]] == [
        "sex",
        "survival",
        "survival_lower",
        "survival_upper",
    ]
    view = await stack.call(
        "create_widget",
        operator_id=finland["id"],
        type="table",
        title="Lung cancer survival in Finland, 2020-2024",
        spec={"columns": ["sex", "survival"]},
        session_id=session["id"],
        note="Men and women side by side",
    )
    widget = view["widget"]
    assert view["url"] == (
        f"/projects/{project['id']}/sessions/{session['id']}?widget={widget['id']}"
    )

    # What the widget shows, fetched by the widget itself, never through the agent.
    data = await stack.call("get_widget_data", widget_id=widget["id"])
    assert [column["name"] for column in data["columns"]] == [
        "sex",
        "survival",
        "survival_lower",
        "survival_upper",
    ]
    # The spec's Nordic comparison: Finland 17.9 (men) and 30.8 (women).
    assert [row[:2] for row in data["rows"]] == [[1, 17.9], [2, 30.8]]
    assert (data["is_scenario"], data["is_stale"], data["truncated"]) == (False, False, False)

    # The session records what the agent did, as the agent, with its notes.
    async with stack.api() as request:
        entries = await (await request.get(SessionService)).entries(UUID(session["id"]))
    assert [(entry.kind.value, entry.text) for entry in entries] == [
        ("operator", "Survival by country, sex and period"),
        ("operator", "Finland, latest period"),
        ("widget", "Men and women side by side"),
    ]
    assert {(entry.actor.kind.value, entry.actor.name) for entry in entries} == {
        ("external_agent", AGENT)
    }

    # Every event went out after the work it names had been committed.
    assert stack.events.unseen == []
    assert stack.events.types == [
        EventType.SESSION_CREATED,
        EventType.SOURCE_REFRESHED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.WIDGET_CREATED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.RUN_STARTED,
        EventType.RUN_FINISHED,
    ]
    refreshed_event = stack.events.bus.published[1]
    assert refreshed_event.payload == {"data_source_id": source["id"], "changed": True}
