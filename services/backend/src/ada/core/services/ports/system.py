from typing import Protocol

from ada.core.models.health import Health


class SystemStatusService(Protocol):
    async def health(self) -> Health: ...

    async def record_heartbeat(self) -> None: ...
