from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from ada.adapters.valkey.events import ValkeyEventPublisher, ValkeyEventStream
from ada.adapters.valkey.tasks import ValkeyTaskDispatcher, stream_broker
from ada.config import Settings
from ada.core.ports.events import EventPublisher, EventStream
from ada.core.ports.tasks import TaskDispatcher

# Re-exported for the entrypoints: tach.toml lets them depend on the composition root but
# not on ada.core.ports, and the event stream (HTTP) and the dispatcher (worker) are ports
# they resolve from the container.
__all__ = ["EventPublisher", "EventStream", "TaskDispatcher", "provider"]


class BackgroundProvider(Provider):
    """Live events and handing work to the worker, both through Valkey. The API, the worker
    and the scheduler build the same container, so an event published in the worker
    reaches the streams the API has open, and a task queued by the API reaches the worker.

    Tests that must not touch Valkey override these with the in-memory implementations
    (ada.adapters.memory)."""

    scope = Scope.APP

    @provide
    def publisher(self, valkey: Redis) -> EventPublisher:
        return ValkeyEventPublisher(valkey)

    @provide
    def stream(self, valkey: Redis) -> EventStream:
        return ValkeyEventStream(valkey)

    @provide
    async def dispatcher(self, settings: Settings) -> AsyncIterator[TaskDispatcher]:
        # Its own broker rather than the worker's: the API and the scheduler have none, and
        # in the worker this one only sends.
        dispatcher = ValkeyTaskDispatcher(stream_broker(settings.valkey_url))
        await dispatcher.startup()
        yield dispatcher
        await dispatcher.shutdown()


provider = BackgroundProvider()
