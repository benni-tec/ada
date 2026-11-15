from typing import Protocol

from ada.core.models.alerts import Alert, AlertDelivery, AlertRule
from ada.core.models.base import Id, JsonObject


class AlertNotifier(Protocol):
    @property
    def configured(self) -> bool: ...

    async def firing(
        self, rule: AlertRule, alert: Alert, rows: list[JsonObject], *, test: bool = False
    ) -> None:
        """Schedule a committed alert for background delivery without waiting or raising."""
        ...


class DeliveryRepository(Protocol):
    async def add(self, delivery: AlertDelivery) -> None: ...

    async def list(self, project_id: Id) -> list[AlertDelivery]: ...
