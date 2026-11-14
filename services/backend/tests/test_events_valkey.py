"""Events through Valkey pub/sub. Every test uses a project id of its own, so its channel is
its own too."""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from uuid import uuid7

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

import factories
from ada.adapters.valkey.events import ValkeyEventPublisher, ValkeyEventStream, channel
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.base import Id
from ada.core.models.events import Event, EventType
from ada.core.ports.events import EventPublisher, EventStream

pytestmark = pytest.mark.anyio

# The Valkey of `moon run root:infra`; moon sets the same value.
VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6380/0")


def event(project_id: Id, type: EventType = EventType.RUN_FINISHED) -> Event:
    return Event(
        type=type,
        project_id=project_id,
        payload={"run_id": str(uuid7()), "operator_id": "op_abc"},
        at=factories.NOW,
    )


async def subscribers(valkey: Redis, project_id: Id) -> int:
    [(_, count)] = await valkey.pubsub_numsub(channel(project_id))
    return count


async def until_subscribed(valkey: Redis, project_id: Id, count: int = 1) -> None:
    """Pub/sub keeps nothing, so a test publishes only once the subscription is live."""
    async with asyncio.timeout(5):
        # Polled: the subscription is someone else's state, with nothing to wait on.
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


async def test_a_published_event_reaches_the_projects_subscribers(valkey: Redis) -> None:
    project_id, other_project_id = uuid7(), uuid7()
    publisher, stream = ValkeyEventPublisher(valkey), ValkeyEventStream(valkey)
    events = stream.subscribe(project_id)
    received = asyncio.ensure_future(anext(events))
    try:
        await until_subscribed(valkey, project_id)
        # Another project's event goes to another channel.
        await publisher.publish(event(other_project_id))
        sent = event(project_id)
        await publisher.publish(sent)
        assert await asyncio.wait_for(received, 5) == sent
    finally:
        await stop(received, events)
    # Stopping the iteration ends the subscription.
    await until_subscribed(valkey, project_id, count=0)


async def test_a_malformed_message_is_skipped(valkey: Redis) -> None:
    project_id = uuid7()
    events = ValkeyEventStream(valkey).subscribe(project_id)
    received = asyncio.ensure_future(anext(events))
    try:
        await until_subscribed(valkey, project_id)
        await valkey.publish(channel(project_id), "not an event")
        sent = event(project_id, EventType.SOURCE_REFRESHED)
        await ValkeyEventPublisher(valkey).publish(sent)
        assert await asyncio.wait_for(received, 5) == sent
    finally:
        await stop(received, events)


async def test_cancelling_a_subscriber_ends_its_subscription(valkey: Redis) -> None:
    # What happens when a client of the event stream disconnects.
    project_id = uuid7()

    async def consume() -> None:
        async for _ in ValkeyEventStream(valkey).subscribe(project_id):
            pass

    consumer = asyncio.create_task(consume())
    await until_subscribed(valkey, project_id)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    await until_subscribed(valkey, project_id, count=0)


async def test_events_published_in_one_container_reach_streams_of_another(
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
            await until_subscribed(valkey, project_id)
            sent = event(project_id, EventType.RUN_STARTED)
            await (await worker.get(EventPublisher)).publish(sent)
            assert await asyncio.wait_for(received, 5) == sent
        finally:
            await stop(received, events)
    finally:
        await worker.close()
        await api.close()


async def test_publishing_does_not_raise_when_valkey_is_unreachable(
    unreachable_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    container = create_container(unreachable_settings)
    try:
        publisher = await container.get(EventPublisher)
        assert isinstance(publisher, ValkeyEventPublisher)
        with caplog.at_level(logging.WARNING):
            await publisher.publish(event(uuid7()))
        assert "Dropped run.finished event" in caplog.text
    finally:
        await container.close()
