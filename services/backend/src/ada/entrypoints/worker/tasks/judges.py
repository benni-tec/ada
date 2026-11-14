import logging
from uuid import UUID

from dishka.integrations.taskiq import FromDishka

from ada.core.services.ports.judges import WidgetReviewService
from ada.entrypoints.worker.registry import task

logger = logging.getLogger(__name__)


@task()
async def judge_widget(widget_id: str, *, reviews: FromDishka[WidgetReviewService]) -> None:
    """Queued when a text widget is created or changed. The project's judge reads it on a
    fresh run with its inputs resolved, and the verdict is stored on the widget."""
    try:
        await reviews.review(UUID(widget_id))
    except Exception:
        # The judge itself never fails (an unchecked verdict instead); this is the widget
        # gone, or its run failing. The widget then stays without a verdict.
        logger.exception("Reviewing widget %s failed", widget_id)
