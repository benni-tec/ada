from datetime import UTC, datetime

from ada.core.ports.system import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)
