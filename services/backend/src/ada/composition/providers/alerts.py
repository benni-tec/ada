from dishka import Provider, Scope, provide

from ada.core.services.alerts.service import Alerts
from ada.core.services.ports.alerts import AlertService


class AlertProvider(Provider):
    """Alert rules and their checks."""

    scope = Scope.REQUEST

    alerts = provide(Alerts, provides=AlertService)


provider = AlertProvider()
