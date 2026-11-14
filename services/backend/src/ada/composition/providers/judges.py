from dishka import Provider, Scope, provide

from ada.core.services.judges.unchecked import UncheckedJudges
from ada.core.services.ports.judges import JudgeService


class JudgesProvider(Provider):
    """The judges that review what agents write. Unchecked until they are built."""

    judges = provide(UncheckedJudges, provides=JudgeService, scope=Scope.REQUEST)


provider = JudgesProvider()
