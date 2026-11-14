import logging
from collections.abc import Awaitable, Callable

from ada.core.models.events import Event
from ada.core.ports.events import EventBroadcaster, EventPublisher
from ada.core.ports.transactions import AfterCommit

logger = logging.getLogger(__name__)


class PendingWork(AfterCommit):
    """The actions of one unit of work that wait for its commit. Whoever owns the
    transaction calls `discard` when it rolls back, and `run` once it has committed."""

    def __init__(self) -> None:
        self._actions: list[Callable[[], Awaitable[None]]] = []
        self._discarded = False

    def add(self, action: Callable[[], Awaitable[None]]) -> None:
        if not self._discarded:
            self._actions.append(action)

    def discard(self) -> None:
        self._discarded = True
        self._actions.clear()

    async def run(self) -> None:
        actions, self._actions = self._actions, []
        for action in actions:
            try:
                await action()
            except Exception:
                # The data is committed; failing now would only hide that it is.
                logger.exception("An action after the commit failed")


class TransactionalEventPublisher(EventPublisher):
    """Holds a unit of work's events and broadcasts them, in order, after its commit."""

    def __init__(self, after_commit: AfterCommit, broadcaster: EventBroadcaster) -> None:
        self.after_commit = after_commit
        self.broadcaster = broadcaster

    async def publish(self, event: Event) -> None:
        async def broadcast() -> None:
            await self.broadcaster.publish(event)

        self.after_commit.add(broadcast)
