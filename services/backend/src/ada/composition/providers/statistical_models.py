from dishka import Provider, Scope, provide

from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.statistical_models.service import StatisticalModels


class StatisticalModelProvider(Provider):
    scope = Scope.REQUEST

    models = provide(StatisticalModels, provides=StatisticalModelService)


provider = StatisticalModelProvider()
