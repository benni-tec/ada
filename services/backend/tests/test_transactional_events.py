"""Events are broadcast once the unit of work that caused them has committed, and dropped
when it fails, whether the unit is an HTTP request, an MCP tool call or a worker task."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from dishka import AsyncContainer, FromDishka, Provider, Scope
from dishka.integrations.taskiq import inject as inject_task
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from taskiq import InMemoryBroker

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.ports.events import EventBroadcaster, EventPublisher
from ada.core.ports.repositories import ProjectRepository
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.injection import make_inject
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker.factory import ContainerMiddleware
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio


def event(project_id: Any) -> Event:
    return Event(type=EventType.RUN_STARTED, project_id=project_id, at=factories.NOW)


@pytest.fixture
async def container(unreachable_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = create_container(unreachable_settings, *memory_adapters())
    yield container
    await container.close()


async def published(container: AsyncContainer) -> list[Event]:
    return (await container.get(MemoryEventBus)).published


async def test_an_event_is_broadcast_when_the_unit_of_work_ends(
    container: AsyncContainer,
) -> None:
    sent = event(uuid7())
    async with container() as request:
        await (await request.get(EventPublisher)).publish(sent)
        assert await published(container) == []
    assert await published(container) == [sent]


async def test_an_event_of_failed_work_is_dropped(container: AsyncContainer) -> None:
    with pytest.raises(RuntimeError):
        async with container() as request:
            await (await request.get(EventPublisher)).publish(event(uuid7()))
            raise RuntimeError("the work failed")
    assert await published(container) == []


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
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    container = create_container(settings, MemoryBackground(), provider)
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
            await (await request.get(EventPublisher)).publish(event(project.id))
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


async def test_a_rest_request_answered_with_an_error_rolls_back_and_announces_nothing(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    with TestClient(create_app(settings, MemoryBackground())) as client:
        project = client.post("/api/projects", json={"name": "P"}).json()
        session = client.post(
            f"/api/projects/{project['id']}/sessions", json={"title": "Old"}
        ).json()
        # Renames, then fails on the unknown dashboard: the rename must not stay.
        response = client.patch(
            f"/api/sessions/{session['id']}",
            json={"title": "New", "panel_dashboard_id": str(uuid7()), "expected_revision": 1},
        )
        assert response.status_code == 404
        assert client.get(f"/api/sessions/{session['id']}").json()["title"] == "Old"

        container = client.app.state.dishka_container  # type: ignore[attr-defined]
        assert client.portal is not None
        bus = client.portal.call(container.get, MemoryEventBus)
        # Only the successful requests announced anything.
        assert [e.type for e in bus.published] == [EventType.SESSION_CREATED]


async def test_an_mcp_tool_that_fails_announces_nothing(container: AsyncContainer) -> None:
    mcp = create_mcp(container)
    inject = make_inject(container)

    @mcp.tool
    @inject
    async def announce(fail: bool, events: FromDishka[EventPublisher]) -> str:
        await events.publish(event(uuid7()))
        if fail:
            raise Invalid("the tool failed")
        return "done"

    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("announce", {"fail": True})
        assert await published(container) == []
        await client.call_tool("announce", {"fail": False})
    assert len(await published(container)) == 1


async def test_a_worker_task_that_fails_announces_nothing(container: AsyncContainer) -> None:
    broker = InMemoryBroker()
    broker.add_middlewares(ContainerMiddleware(container))

    async def announce(fail: bool, events: FromDishka[EventPublisher]) -> None:
        await events.publish(event(uuid7()))
        if fail:
            raise RuntimeError("the task failed")

    task = broker.register_task(inject_task(announce, patch_module=True), "test:announce")
    await broker.startup()
    try:
        await (await task.kiq(fail=True)).wait_result()
        assert await published(container) == []
        await (await task.kiq(fail=False)).wait_result()
        assert len(await published(container)) == 1
    finally:
        await broker.shutdown()
