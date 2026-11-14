from dishka import Provider, Scope, provide

from ada.composition.unbuilt import unbuilt
from ada.core.services.ports.alerts import AlertService


class AlertProvider(Provider):
    """Alert rules and their checks."""

    scope = Scope.REQUEST

    alerts = provide(unbuilt(AlertService))


provider = AlertProvider()
