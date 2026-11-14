from dishka import Provider, Scope, provide

from ada.composition.unbuilt import unbuilt
from ada.core.services.ports.reports import ReportService, TemplateService


class ReportProvider(Provider):
    """Reports, their versions, and templates."""

    scope = Scope.REQUEST

    reports = provide(unbuilt(ReportService))
    templates = provide(unbuilt(TemplateService))


provider = ReportProvider()
