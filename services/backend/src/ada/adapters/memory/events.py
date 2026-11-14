import asyncio
from collections.abc import AsyncIterator

from ada.core.models.base import Id
from ada.core.models.events import Event
from ada.core.ports.events import EventPublisher, EventStream


class MemoryEventBus(EventPublisher, EventStream):
    """Publisher and stream in one process. Events reach only subscribers of this
    instance, so it suits a single process and tests; several processes need a broker."""

    def __init__(self) -> None:
        self._subscribers: dict[Id, set[asyncio.Queue[Event]]] = {}
        # Everything published, for tests to assert on.
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        for queue in self._subscribers.get(event.project_id, ()):
            queue.put_nowait(event)

    async def subscribe(self, project_id: Id) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        subscribers = self._subscribers.setdefault(project_id, set())
        subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers.discard(queue)
