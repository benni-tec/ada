from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import MAIN_INPUT, Widget, WidgetData
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.apps import ANY_WIDGET
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.links import widget_url
from ada.entrypoints.mcp.sessions import SessionId

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
        session_id: SessionId,
        operator_id: OperatorId,
        type: str,
        title: str,
        pipelines: FromDishka[PipelineService],
        widgets: FromDishka[WidgetService],
        spec: JsonObject | None = None,
        note: str = "",
        inputs: dict[str, OperatorId] | None = None,
    ) -> WidgetView:
        """Show an operator's output to the person you work with. Pass only the operator
        id: the widget fetches its own data from the platform, so no numbers go through
        you and none can be misquoted.

        `type` picks the display, and `spec` holds its settings, all optional:

        - "value", one number: `column` (default: the first measure role, else the first
          numeric column), `label` (default: the column name), `unit` (e.g. "%"),
          `decimals`, `format`, `compare_to` (a numeric column of the same row, or a
          number such as a target: shown as "+1,346 against 11,970"). Shows the latest
          period when the output has a time role, otherwise the last row, so filter or
          aggregate in SQL first.
        - "table": `columns`, the column names to show, in order (default: all);
          `labels`, header text per column ({"cases": "Cases"}); `format`, a number
          format per column ({"share": "percent"}); `decimals`.
        - "line-chart": `x` (default: the time role's start, else the first date column),
          `y`, one column (default: the first measure role, else the first numeric
          column), `series`, a column whose values split the lines, e.g. a region.
        - "map", a choropleth of one value per region: `value` (default: the first
          measure role, else the first numeric column), `geometry` (default "geometry":
          the region outlines as GeoJSON, joined from the boundaries reference source),
          `label` (default: a column "name"). Needs a geography role at one level; shows
          each region's latest period.
        - "chart", any chart: `spec` is a Vega-Lite 6.5 spec (vega-lite 6.5.0, vega
          6.4.0) without `data`. The operator's rows are put in as `data.values`, one
          object per row keyed by column name, dates as ISO strings (use "temporal").
          The top needs a `mark`, `layer`, `concat`/`hconcat`/`vconcat`, `facet` or
          `repeat`; refused: `data`, `datasets`, `url` and `href` anywhere, `usermeta`.
          A single view fills the frame; transforms, params and expressions work.
          A line with a target:
          {"layer": [{"mark": "line", "encoding": {
             "x": {"field": "year", "type": "ordinal"},
             "y": {"field": "cases", "type": "quantitative"}}},
           {"mark": {"type": "rule", "strokeDash": [4, 4]},
            "encoding": {"y": {"datum": 80}}}]}
          Bars with labels:
          {"encoding": {"x": {"field": "region", "type": "nominal", "sort": "-y"},
                        "y": {"field": "value", "type": "quantitative"}},
           "layer": [{"mark": "bar"},
            {"mark": {"type": "text", "dy": -6},
             "encoding": {"text": {"field": "value", "format": ".1f"}}}]}

        Number formats are "integer", "number", "percent" (the value is already in
        percent: 72.5 gives "72.5 %") or "plain" (no thousands separator). Integer
        columns named `year` or `*_year`, and the time role's columns, are plain anyway.

        A widget whose operator lacks what its type needs is refused, with every problem
        named: a column the spec names must exist (and be numeric where a number is
        shown), and a map needs a geography role and its outlines. Declare roles on the
        transform (`add_transform`) or pick another type.

        A widget marks simulated and outdated data by itself.

        `inputs` names further operators of the project the widget reads besides its own,
        e.g. {"targets": "<operator id>"}: lowercase names (letters, digits, _), at most 8;
        its own operator is the input "main". All are read in the same run and frozen
        together in reports. Only types that show several datasets read them; the others
        ignore them.

        Give a one-line `note` on what the widget shows and why: the session shows the
        widget with the note on its card. Returns the widget and its `url`: give
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
            inputs=inputs,
        )
        return WidgetView(widget=widget, url=widget_url(widget))

    @mcp.tool(app=AppConfig(resource_uri=ANY_WIDGET))
    @inject
    async def update_widget(
        session_id: SessionId,
        widget_id: Id,
        widgets: FromDishka[WidgetService],
        title: str | None = None,
        note: str | None = None,
        type: str | None = None,
        spec: JsonObject | None = None,
        inputs: dict[str, OperatorId] | None = None,
    ) -> WidgetView:
        """Change a widget in place: its title, note, type, spec or further inputs; what you
        leave out stays. New `inputs` replace the old ones whole ({} removes them all).
        A new `spec` replaces the old one whole (send all of it) and is checked against the
        operator as in `create_widget`, whose description lists every type's settings. Use
        it to fix a chart or add labels instead of creating a second widget. The widget's
        operator cannot change: for other data, create a widget. A copy on a dashboard is a
        widget of its own (its id is in the dashboard's slots) and does not change with the
        original. Returns the widget and its `url`."""
        widget = await widgets.update(
            widget_id, title=title, note=note, type=type, spec=spec, inputs=inputs
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
        input: str = MAIN_INPUT,
    ) -> WidgetData:
        """The data a widget shows: one input's output in a run ("main", its own operator,
        unless `input` names another), with what the columns mean and whether the numbers
        are simulated or stale. Called by the widget, not by the model. Without `run_id` a
        new run is started; read further inputs with the `run_id` of the first answer."""
        return await widgets.data(widget_id, run_id, limit, input)

    @mcp.tool
    @inject
    async def list_session_widgets(
        session_id: SessionId, widgets: FromDishka[WidgetService]
    ) -> Sequence[WidgetView]:
        """List the widgets shown in a session, each with its url. Use it to see what has
        already been shown before adding more, or to point the person to one."""
        return [
            WidgetView(widget=widget, url=widget_url(widget))
            for widget in await widgets.list_by_session(session_id)
        ]
