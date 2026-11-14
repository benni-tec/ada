from collections.abc import AsyncIterator
from typing import Protocol

from ada.core.models.base import Id
from ada.core.models.events import Event


class EventPublisher(Protocol):
    """What services publish through. An event announces stored work, so it is delivered
    once the work's transaction commits and dropped when it rolls back: a client that
    fetches on an event finds what the event names, and failed work announces nothing."""

    async def publish(self, event: Event) -> None:
        """Tell everyone watching the event's project. Never raises: a lost event must not
        fail the work that caused it."""
        ...


class EventBroadcaster(Protocol):
    """Delivers an event to every process at once, e.g. through Valkey. Only the
    composition uses it, behind the transactional EventPublisher; services never do."""

    async def publish(self, event: Event) -> None:
        """Never raises, like EventPublisher.publish."""
        ...


class EventStream(Protocol):
    def subscribe(self, project_id: Id) -> AsyncIterator[Event]:
        """Events of one project, from now on, until the caller stops iterating."""
        ...
