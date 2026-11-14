from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id
from ada.core.services.ports.judges import WidgetReviewService
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.links import widget_url
from ada.entrypoints.mcp.sessions import SessionId
from ada.entrypoints.mcp.tools.widgets import WidgetView


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def review_widget(
        session_id: SessionId,
        widget_id: Id,
        reviews: FromDishka[WidgetReviewService],
        run_id: Id | None = None,
    ) -> WidgetView:
        """Have the project's judge review a text widget (or a custom widget's code) now,
        and wait for its verdict. A text widget is reviewed by itself after
        `create_widget` and `update_widget`; call this to see the verdict at once, e.g.
        after fixing what it found. The judge reads the text with every placeholder
        resolved, on `run_id` or a new run, against the inputs' rows. It reports figures
        written into the text instead of a placeholder and statements the data
        contradicts (errors), and claims the data cannot decide (warnings).

        Returns the widget with `verdict`: `outcome` pass, warn, fail or unchecked (no
        model is configured, the judge is off, or its call failed: `reason`), and
        `findings`, each with the `excerpt` it is about and a `message` saying what to do.
        Fix the findings with `update_widget`. A judge with strictness "block" refuses
        report versions that show a failing text widget."""
        widget = await reviews.review(widget_id, run_id)
        return WidgetView(widget=widget, url=widget_url(widget))
