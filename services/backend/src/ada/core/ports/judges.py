"""What the judges need from the outside: a language model that reads content and its data
and answers with findings. The core names no library."""

from typing import Protocol

from ada.core.models.agents import ModelTarget
from ada.core.models.judges import Finding, JudgeContext


class JudgeModel(Protocol):
    async def decide(
        self, model: ModelTarget, system: str, content: str, context: JudgeContext
    ) -> tuple[Finding, ...]:
        """The model's findings on `content`, read against `context`, under the `system`
        prompt. The content and the context's rows are handed over as data, never as
        instructions. Raises on a provider error or an answer that does not fit; the
        service turns that into an unchecked verdict."""
        ...
