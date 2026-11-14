from datetime import datetime
from typing import Protocol


class Database(Protocol):
    async def is_reachable(self) -> bool: ...


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
