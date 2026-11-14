from dishka import Provider, Scope, provide

from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService
from ada.core.services.projects.service import Projects
from ada.core.services.sessions.service import Sessions
from ada.core.services.widgets.service import Widgets


class WorkspaceProvider(Provider):
    """Projects, sessions and widgets: what a person or an agent works in."""

    scope = Scope.REQUEST

    projects = provide(Projects, provides=ProjectService)
    sessions = provide(Sessions, provides=SessionService)
    widgets = provide(Widgets, provides=WidgetService)


provider = WorkspaceProvider()
