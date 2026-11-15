from collections.abc import Collection
from datetime import datetime
from typing import Protocol
from uuid import UUID


class Database(Protocol):
    async def is_reachable(self) -> bool: ...


class ProjectOwners(Protocol):
    async def of(self, ids: Collection[UUID]) -> set[UUID]:
        """The projects these ids belong to: a project's own id, or the project of any row
        with that id. Ids of no row are left out."""
        ...


class TaskQueue(Protocol):
    async def is_reachable(self) -> bool: ...

    async def record_heartbeat(self) -> None:
        """Called by the scheduled heartbeat task; proves scheduler, queue and worker work."""
        ...

    async def worker_is_alive(self) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware in UTC."""
        ...
