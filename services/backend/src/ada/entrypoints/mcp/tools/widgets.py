from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import Widget
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.links import widget_url


class WidgetView(DomainModel):
    widget: Widget
    # Where a person sees it in the frontend, relative to the host serving ADA.
    url: str


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def create_widget(
        operator_id: OperatorId,
        type: str,
        title: str,
        pipelines: FromDishka[PipelineService],
        widgets: FromDishka[WidgetService],
        spec: JsonObject | None = None,
        session_id: Id | None = None,
        note: str = "",
    ) -> WidgetView:
        """Show an operator's output to the person you work with. Pass only the operator
        id: the widget fetches its own data from the platform, so no numbers go through
        you and none can be misquoted.

        `type` picks the display, e.g. "value" (one number), "table" or "line-chart".
        `spec` holds that type's settings, e.g. which column is the x axis. A widget marks
        simulated and outdated data by itself.

        Pass `session_id` and a one-line `note` on what the widget shows and why, to put it
        in that session, with the note on its card. Returns the widget and its `url`: give
        the url to the person."""
        operator = await pipelines.get(operator_id)
        widget = await widgets.create(
            operator.project_id,
            operator_id,
            type,
            title,
            calling_agent(),
            spec=spec,
            note=note,
            session_id=session_id,
        )
        return WidgetView(widget=widget, url=widget_url(widget))

    @mcp.tool
    @inject
    async def list_session_widgets(
        session_id: Id, widgets: FromDishka[WidgetService]
    ) -> Sequence[WidgetView]:
        """List the widgets shown in a session, each with its url. Use it to see what has
        already been shown before adding more, or to point the person to one."""
        return [
            WidgetView(widget=widget, url=widget_url(widget))
            for widget in await widgets.list_by_session(session_id)
        ]
