from dishka import Provider, Scope, provide

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.config import Settings
from ada.core.ports.analysis import AnalysisStore
from ada.core.services.pipelines.batch import Batches
from ada.core.services.pipelines.exploration import Exploration
from ada.core.services.pipelines.runs import Runs
from ada.core.services.pipelines.service import Pipelines
from ada.core.services.ports.batches import BatchService
from ada.core.services.ports.exploration import ExplorationService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService


class AnalysisProvider(Provider):
    """The analysis store and the services that plan, run, explore and build pipelines
    on it."""

    @provide(scope=Scope.APP)
    def analysis_store(self, settings: Settings) -> AnalysisStore:
        return DuckDbAnalysisStore(settings.data_dir)

    pipelines = provide(Pipelines, provides=PipelineService, scope=Scope.REQUEST)
    runs = provide(Runs, provides=RunService, scope=Scope.REQUEST)
    exploration = provide(Exploration, provides=ExplorationService, scope=Scope.REQUEST)
    batches = provide(Batches, provides=BatchService, scope=Scope.REQUEST)


provider = AnalysisProvider()
