from dishka import Provider, Scope, provide

from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.core.ports.events import EventPublisher, EventStream
from ada.core.ports.tasks import TaskDispatcher


class BackgroundProvider(Provider):
    """Live events and handing work to the worker. In one process until the Valkey
    implementations exist: events then reach every process, and tasks are really queued."""

    scope = Scope.APP

    bus = provide(MemoryEventBus)
    dispatcher = provide(RecordingTaskDispatcher, provides=TaskDispatcher)

    @provide
    def publisher(self, bus: MemoryEventBus) -> EventPublisher:
        return bus

    @provide
    def stream(self, bus: MemoryEventBus) -> EventStream:
        return bus


provider = BackgroundProvider()
