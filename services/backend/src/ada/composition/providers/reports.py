from dishka import Provider, Scope, provide

from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.reports.service import Reports
from ada.core.services.reports.templates import Templates


class ReportProvider(Provider):
    """Reports, their versions, and templates."""

    scope = Scope.REQUEST

    reports = provide(Reports, provides=ReportService)
    templates = provide(Templates, provides=TemplateService)


provider = ReportProvider()
