import asyncio
import logging
from collections.abc import AsyncIterator

from pydantic import ValidationError
from redis.asyncio import Redis

from ada.core.models.base import Id
from ada.core.models.events import Event
from ada.core.ports.events import EventBroadcaster, EventStream

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ada:events:"


def channel(project_id: Id) -> str:
    """One pub/sub channel per project, so a stream receives only the events it shows."""
    return f"{CHANNEL_PREFIX}{project_id}"


class ValkeyEventPublisher(EventBroadcaster):
    """Publishes to Valkey, so the event reaches the streams of every API process, whichever
    process (API, worker) caused it. Pub/sub keeps nothing: a client that is not connected
    misses the event and refetches when it reconnects."""

    def __init__(self, valkey: Redis) -> None:
        self.valkey = valkey

    async def publish(self, event: Event) -> None:
        try:
            await self.valkey.publish(channel(event.project_id), event.model_dump_json())
        except Exception:
            # The port promises not to raise: the work that caused the event is done and
            # must not fail because nobody could be told about it.
            logger.warning("Dropped %s event of project %s", event.type, event.project_id)


class ValkeyEventStream(EventStream):
    """Subscribes to a project's channel. Each subscription holds its own connection for as
    long as the caller iterates."""

    def __init__(self, valkey: Redis) -> None:
        self.valkey = valkey

    async def subscribe(self, project_id: Id) -> AsyncIterator[Event]:
        # The subscription starts with the first iteration; events published before that
        # are not delivered.
        pubsub = self.valkey.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(channel(project_id))
            # Blocks without the client's socket timeout: a quiet project is normal.
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = Event.model_validate_json(message["data"])
                except ValidationError:
                    # Someone else's message on our channel; skipping it keeps the stream
                    # open.
                    logger.warning("Skipped a malformed event on %s", channel(project_id))
                    continue
                yield event
        finally:
            # Closing drops the subscription with the connection. This mostly runs because
            # the caller was cancelled (a client went away), and under anyio every await
            # of a cancelled task is cancelled again; shielding lets the close finish and
            # the connection go back to the pool.
            await asyncio.shield(pubsub.aclose())
