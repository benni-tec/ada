from typing import Protocol

from ada.core.models.alerts import Alert, AlertRule
from ada.core.models.base import JsonObject


class AlertNotifier(Protocol):
    @property
    def configured(self) -> bool: ...

    async def firing(self, rule: AlertRule, alert: Alert, rows: list[JsonObject]) -> None:
        """Schedule a committed alert for background delivery without waiting or raising."""
        ...
