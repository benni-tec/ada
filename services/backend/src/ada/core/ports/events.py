from collections.abc import AsyncIterator
from typing import Protocol

from ada.core.models.base import Id
from ada.core.models.events import Event


class EventPublisher(Protocol):
    async def publish(self, event: Event) -> None:
        """Tell everyone watching the event's project. Never raises: a lost event must not
        fail the work that caused it."""
        ...


class EventStream(Protocol):
    def subscribe(self, project_id: Id) -> AsyncIterator[Event]:
        """Events of one project, from now on, until the caller stops iterating."""
        ...
