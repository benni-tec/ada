from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from ada.adapters.transactions import TransactionalEventPublisher
from ada.adapters.valkey.events import ValkeyEventPublisher, ValkeyEventStream
from ada.adapters.valkey.tasks import ValkeyTaskDispatcher, stream_broker
from ada.config import Settings
from ada.core.ports.events import EventBroadcaster, EventPublisher, EventStream
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit


class BackgroundProvider(Provider):
    """Live events and handing work to the worker, both through Valkey. The API, the worker
    and the scheduler build the same container, so an event published in the worker
    reaches the streams the API has open, and a task queued by the API reaches the worker.

    Services publish through a request-scoped publisher that holds each event until the
    request's transaction commits (ada.adapters.transactions); only then is it broadcast.

    Tests that must not touch Valkey override the broadcaster, the stream and the dispatcher
    with the in-memory implementations (ada.adapters.memory)."""

    scope = Scope.APP

    @provide
    def broadcaster(self, valkey: Redis) -> EventBroadcaster:
        return ValkeyEventPublisher(valkey)

    @provide(scope=Scope.REQUEST)
    def publisher(self, after_commit: AfterCommit, broadcaster: EventBroadcaster) -> EventPublisher:
        return TransactionalEventPublisher(after_commit, broadcaster)

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
