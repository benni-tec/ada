from dishka import Provider, Scope, provide

from ada.adapters.llm.judge import PydanticAiJudge
from ada.core.ports.judges import JudgeModel
from ada.core.services.judges.service import Judges, VerdictCache
from ada.core.services.ports.judges import JudgeService, WidgetReviewService
from ada.core.services.widgets.review import WidgetReviews


class JudgesProvider(Provider):
    """The judges that review what agents write: the service and its settings, the model
    behind it (pydantic-ai), the verdicts cached per process, and the review of widgets."""

    @provide(scope=Scope.APP)
    def model(self) -> JudgeModel:
        return PydanticAiJudge()

    cache = provide(VerdictCache, scope=Scope.APP)
    judges = provide(Judges, provides=JudgeService, scope=Scope.REQUEST)
    reviews = provide(WidgetReviews, provides=WidgetReviewService, scope=Scope.REQUEST)


provider = JudgesProvider()
