from dishka import Provider, Scope, provide

from ada.composition.unbuilt import unbuilt
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService


class WorkspaceProvider(Provider):
    """Projects, sessions and widgets: what a person or an agent works in."""

    scope = Scope.REQUEST

    projects = provide(unbuilt(ProjectService))
    sessions = provide(unbuilt(SessionService))
    widgets = provide(unbuilt(WidgetService))


provider = WorkspaceProvider()
