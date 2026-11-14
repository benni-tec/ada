import hashlib
import json

from ada.core.models.base import Id
from ada.core.models.judges import JudgeContext, JudgeKind, Outcome, Verdict
from ada.core.ports.system import Clock


class UncheckedJudges:
    """Every verdict unchecked, until the judges are built: content is never refused."""

    def __init__(self, clock: Clock):
        self.clock = clock

    async def review(
        self, project_id: Id, kind: JudgeKind, content: str, context: JudgeContext
    ) -> Verdict:
        return Verdict(
            kind=kind,
            outcome=Outcome.UNCHECKED,
            passed=False,
            blocking=False,
            reason="judges are not built yet",
            content_hash=content_hash(content, context),
            checked_at=self.clock.now(),
        )


def content_hash(content: str, context: JudgeContext) -> str:
    """sha256 of the content and its context, the key a verdict is cached by."""
    payload = json.dumps([content, context.model_dump(mode="json")], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
