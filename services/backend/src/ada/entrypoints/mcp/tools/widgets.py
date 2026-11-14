from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import Widget, WidgetData
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.apps import ANY_WIDGET
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.links import widget_url

# The same bound as the REST route: rows travel as JSON.
MAX_WIDGET_ROWS = 10_000


class WidgetView(DomainModel):
    widget: Widget
    # Where a person sees it in the frontend, relative to the host serving ADA.
    url: str


def register(mcp: FastMCP, inject: Inject) -> None:
    # A host that supports MCP Apps renders the widget right after the call.
    @mcp.tool(app=AppConfig(resource_uri=ANY_WIDGET))
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

        `type` picks the display, and `spec` holds its settings, all optional:

        - "value", one number: `column` (default: the first measure role, else the first
          numeric column), `label` (default: the column name), `unit` (e.g. "%"),
          `decimals`. Shows the latest period when the output has a time role, otherwise
          the last row, so filter or aggregate in SQL first.
        - "table": `columns`, the column names to show, in order (default: all).
        - "line-chart": `x` (default: the time role's start, else the first date column),
          `y`, one column (default: the first measure role, else the first numeric
          column), `series`, a column whose values split the lines, e.g. a region.

        A widget marks simulated and outdated data by itself.

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

    # For the widget itself, inside an MCP host: the model never needs the numbers.
    @mcp.tool(app=AppConfig(visibility=["app"]))
    @inject
    async def get_widget_data(
        widget_id: Id,
        widgets: FromDishka[WidgetService],
        run_id: Id | None = None,
        limit: Annotated[int, Field(ge=1, le=MAX_WIDGET_ROWS)] = 1000,
    ) -> WidgetData:
        """The data a widget shows: its operator's output in a run, with what the columns
        mean and whether the numbers are simulated or stale. Called by the widget, not by
        the model. Without `run_id` a new run is started."""
        return await widgets.data(widget_id, run_id, limit)

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
