from dishka import Provider, Scope, provide

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.composition.unbuilt import unbuilt
from ada.config import Settings
from ada.core.ports.analysis import AnalysisStore
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService


class AnalysisProvider(Provider):
    """The analysis store and the services that plan and run pipelines on it."""

    @provide(scope=Scope.APP)
    def analysis_store(self, settings: Settings) -> AnalysisStore:
        return DuckDbAnalysisStore(settings.data_dir)

    pipelines = provide(unbuilt(PipelineService), scope=Scope.REQUEST)
    runs = provide(unbuilt(RunService), scope=Scope.REQUEST)


provider = AnalysisProvider()
