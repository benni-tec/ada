from typing import Protocol

from ada.core.models.base import Id
from ada.core.models.judges import JudgeContext, JudgeKind, Verdict


class JudgeService(Protocol):
    async def review(
        self, project_id: Id, kind: JudgeKind, content: str, context: JudgeContext
    ) -> Verdict:
        """Review content with the project's judge of that kind. Never raises for the
        model: a judge that is off, has no model or whose call fails gives an unchecked
        verdict with the reason. Raises NotFound for an unknown project. The caller stores
        the verdict."""
        ...
