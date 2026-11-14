from dishka import Provider, Scope, provide

from ada.composition.unbuilt import unbuilt
from ada.core.services.ports.dashboards import DashboardService


class DashboardProvider(Provider):
    """Dashboards and their versions."""

    scope = Scope.REQUEST

    dashboards = provide(unbuilt(DashboardService))


provider = DashboardProvider()
