from collections.abc import Sequence
from typing import Protocol

from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.judges import (
    JudgeContext,
    JudgeDefaults,
    JudgeKind,
    JudgeSettings,
    Outcome,
    Strictness,
    Verdict,
)
from ada.core.models.widgets import Widget


class JudgeService(Protocol):
    async def review(
        self, project_id: Id, kind: JudgeKind, content: str, context: JudgeContext
    ) -> Verdict:
        """Review content with the project's judge of that kind. Never raises for the
        model: a judge that is off, has no model or whose call fails gives an unchecked
        verdict with the reason. Raises NotFound for an unknown project. Results are
        cached by (content_hash, model, revisions of the defaults and the override). The
        caller stores the verdict."""
        ...

    async def defaults(self) -> Sequence[JudgeDefaults]:
        """The global settings, one per kind."""
        ...

    async def set_defaults(
        self,
        kind: JudgeKind,
        expected_revision: int,
        strictness: Strictness | None = None,
        model_id: Change[str | None] = UNCHANGED,
        instructions: str | None = None,
    ) -> JudgeDefaults:
        """Change a kind's global settings; what is left out stays, `model_id` None clears
        the model. An unknown model is Invalid; a stale revision Conflict."""
        ...

    async def settings(self, project_id: Id) -> Sequence[JudgeSettings]:
        """What review uses in the project, one per kind: the defaults with the project's
        overrides applied."""
        ...

    async def override(
        self,
        project_id: Id,
        kind: JudgeKind,
        expected_revision: int,
        strictness: Change[Strictness | None] = UNCHANGED,
        model_id: Change[str | None] = UNCHANGED,
        instructions: Change[str | None] = UNCHANGED,
    ) -> JudgeSettings:
        """Override a kind's settings in the project. None inherits the global default
        again; what is left out stays. `expected_revision` is JudgeSettings.revision (0
        while the project overrides nothing of this kind)."""
        ...


class WidgetReviewService(Protocol):
    """The judges applied to widgets: text widgets (`text_widget`) and custom widgets'
    code (`widget_code`). The verdict is stored on the widget."""

    async def review(self, widget_id: Id, run_id: Id | None = None) -> Widget:
        """Review the widget with its inputs as they read in `run_id` (a new run when
        None), store the verdict and return the widget. A widget changed while it was
        reviewed keeps its verdict as it was. Other types are Invalid."""
        ...

    async def verdicts(
        self, project_id: Id, kind: JudgeKind | None = None, outcome: Outcome | None = None
    ) -> Sequence[Widget]:
        """The project's widgets that carry a verdict, newest verdict first."""
        ...
