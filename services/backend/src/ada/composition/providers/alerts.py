from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from ada.adapters.db.deliveries import SqlDeliveryRepository
from ada.adapters.notify.http import HttpAlertNotifier
from ada.config import Settings
from ada.core.ports.notify import AlertNotifier, DeliveryRepository
from ada.core.services.alerts.service import Alerts
from ada.core.services.ports.alerts import AlertService


class AlertProvider(Provider):
    """Alert rules and their checks."""

    scope = Scope.REQUEST

    deliveries = provide(SqlDeliveryRepository, provides=DeliveryRepository, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def notifier(
        self, settings: Settings, deliveries: DeliveryRepository
    ) -> AsyncIterator[AlertNotifier]:
        async with httpx.AsyncClient(timeout=5) as client:
            notifier = HttpAlertNotifier(
                client,
                settings.alert_ntfy_url,
                settings.alert_webhook_url,
                settings.ada_public_url,
                settings.alert_email_to,
                deliveries.add,
            )
            try:
                yield notifier
            finally:
                # Let pushes for committed alerts finish before the client closes.
                await notifier.drain()

    alerts = provide(Alerts, provides=AlertService)


provider = AlertProvider()
