from dishka import Provider, Scope, provide

from ada.core.services.dashboards.service import Dashboards
from ada.core.services.ports.dashboards import DashboardService


class DashboardProvider(Provider):
    """Dashboards and their versions."""

    scope = Scope.REQUEST

    dashboards = provide(Dashboards, provides=DashboardService)


provider = DashboardProvider()
