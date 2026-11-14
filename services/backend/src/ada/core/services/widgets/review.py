"""The judges applied to widgets (core/services/judges): what a judge reads of a widget in
a run, and the use cases that review a widget and list the verdicts.

- A text widget (`text_widget`): its Markdown with each placeholder resolved and tagged
  (text.resolve), against every input's columns and rows.
- A custom widget (`widget_code`): its code and CSS, against every input's columns and a
  few rows.
"""

from collections.abc import Sequence

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.judges import JudgeContext, JudgeInput, JudgeKind, Outcome, Verdict
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import Widget
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import OperatorRepository, WidgetRepository
from ada.core.ports.system import Clock
from ada.core.services.ports.judges import JudgeService, WidgetReviewService
from ada.core.services.ports.runs import RunService
from ada.core.services.widgets.service import WIDGET_ACTOR
from ada.core.services.widgets.text import MARKDOWN_KEY, TEXT_TYPE, InputRows, parse, resolve

CUSTOM_TYPE = "custom"
# The kind of judge per widget type; other types are not reviewed.
KINDS = {TEXT_TYPE: JudgeKind.TEXT_WIDGET, CUSTOM_TYPE: JudgeKind.WIDGET_CODE}
# Rows read per input: enough to find a text widget's latest period; the judge service
# caps what the model sees per kind.
_ROWS = {JudgeKind.TEXT_WIDGET: 5_000, JudgeKind.WIDGET_CODE: 20}


class WidgetJudging:
    """Builds what the judge reads of a widget in a run, and asks it. Shared by the review
    of a widget and by report versions, which review on their own run."""

    def __init__(
        self, runs: RunService, operators: OperatorRepository, judges: JudgeService
    ) -> None:
        self.runs = runs
        self.operators = operators
        self.judges = judges

    async def review(self, widget: Widget, run_id: Id) -> Verdict | None:
        """The verdict on the widget as `run_id` reads its inputs; None for a type that is
        not reviewed."""
        kind = KINDS.get(widget.type)
        if kind is None:
            return None
        data = {
            name: await self._read(run_id, operator_id, _ROWS[kind])
            for name, operator_id in widget.all_inputs().items()
        }
        context = JudgeContext(
            inputs=tuple(
                JudgeInput(name=name, columns=rows.columns, rows=rows.rows)
                for name, rows in data.items()
            ),
            note=f'{widget.type} widget: "{widget.title}"',
        )
        if kind is JudgeKind.TEXT_WIDGET:
            markdown = widget.spec.get(MARKDOWN_KEY)
            content = resolve(parse(markdown)[0], data) if isinstance(markdown, str) else ""
        else:
            code, css = widget.spec.get("code"), widget.spec.get("css")
            content = (code if isinstance(code, str) else "") + "\n/* css */\n"
            content += css if isinstance(css, str) else ""
        return await self.judges.review(widget.project_id, kind, content, context)

    async def _read(self, run_id: Id, operator_id: OperatorId, limit: int) -> InputRows:
        operator = await self.operators.get(operator_id)
        try:
            rows = await self.runs.read(run_id, operator_id, limit)
        except Exception:
            # The judge still sees what the input is; a placeholder then has no value.
            return InputRows(output=operator.output, columns=operator.output.columns, rows=())
        return InputRows(
            output=operator.output, columns=rows.columns, rows=rows.rows, truncated=rows.truncated
        )


class WidgetReviews(WidgetReviewService):
    def __init__(
        self,
        widgets: WidgetRepository,
        operators: OperatorRepository,
        runs: RunService,
        judges: JudgeService,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.widgets = widgets
        self.runs = runs
        self.events = events
        self.clock = clock
        self.judging = WidgetJudging(runs, operators, judges)

    async def review(self, widget_id: Id, run_id: Id | None = None) -> Widget:
        widget = await self.widgets.get(widget_id)
        if widget.type not in KINDS:
            raise Invalid(
                f"Only text and custom widgets are reviewed; widget {widget.id} is a "
                f"{widget.type} widget"
            )
        if run_id is None:
            run = await self.runs.start(widget.project_id, WIDGET_ACTOR)
        else:
            run = await self.runs.get(run_id)
            if run.project_id != widget.project_id:
                raise Invalid("The run belongs to another project than the widget")
        verdict = await self.judging.review(widget, run.id)
        current = await self.widgets.get(widget_id)
        if _judged(current) != _judged(widget):
            # Changed while the judge read it: the change queued a review of its own.
            return current
        await store_verdict(self.widgets, self.events, self.clock, current, verdict)
        return current.model_copy(update={"verdict": verdict})

    async def verdicts(
        self, project_id: Id, kind: JudgeKind | None = None, outcome: Outcome | None = None
    ) -> Sequence[Widget]:
        found = [
            widget
            for widget in await self.widgets.list(project_id)
            if widget.verdict is not None
            and (kind is None or widget.verdict.kind is kind)
            and (outcome is None or widget.verdict.outcome is outcome)
        ]
        return sorted(
            found,
            key=lambda widget: (widget.verdict.checked_at, widget.id),  # type: ignore[union-attr]
            reverse=True,
        )


async def store_verdict(
    widgets: WidgetRepository,
    events: EventPublisher,
    clock: Clock,
    widget: Widget,
    verdict: Verdict | None,
) -> None:
    """Store a verdict on the widget and announce the change (the card shows it)."""
    await widgets.set_verdict(widget.id, verdict)
    payload = {"widget_id": str(widget.id)}
    if widget.session_id is not None:
        payload["session_id"] = str(widget.session_id)
    await events.publish(
        Event(
            type=EventType.WIDGET_UPDATED,
            project_id=widget.project_id,
            payload=payload,
            at=clock.now(),
        )
    )


def _judged(widget: Widget) -> tuple[object, ...]:
    """What a verdict is about."""
    return (widget.type, widget.spec, widget.all_inputs())
