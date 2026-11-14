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
        - "custom", your own drawing code, for what no other type can show: `spec` is
          {"code": "<ES module>", "css": "<optional>", "libraries": ["d3", "vega-lite"]
          (optional, either or both)}, no other keys. The module's default export draws,
          `export default function render(root, data, ada)`, and may return a cleanup
          function (or a promise of one), called before the next render. It runs again on
          an emptied `root` after a new run or a theme change; resizing does not, so
          redraw in `ada.onResize(({width, height}) => ...)`.
          `data.main` is the widget's own operator and `data.inputs[name]` each input
          ("main" too): {columns: [{name, type}], rows: [{column: value}] (dates as ISO
          strings), roles (the output's time, geo and measure roles), truncated (more than
          5,000 rows)}; and `data.run_id`, `data.is_scenario`, `data.is_stale`.
          `ada.theme` ("light" or "dark"), `ada.colors` {foreground, muted, background,
          border, accent, positive, negative, warning, series: 8 colours}, `ada.size`
          {width, height}, `ada.format.number(value, {format, decimals})` and
          `ada.format.date(value, {grain: "day" | "month" | "quarter" | "year"})` (the
          platform's formats), `ada.libraries.d3` (d3 7.9) and `ada.libraries.vegaEmbed`
          (vega-embed; a plain Vega-Lite chart is the "chart" type), only those listed,
          and `ada.error(message)` to report a problem without throwing. In `css` the
          colours are variables, `--ada-<name>` for each named one (`--ada-foreground` ...
          `--ada-warning`) and `--ada-series-1` to `--ada-series-8`, and the frame's root
          has `data-theme`.
          It runs in a sandboxed frame without network. Refused anywhere in `code`,
          comments included: fetch, XMLHttpRequest, WebSocket, EventSource, sendBeacon,
          importScripts, document.cookie, localStorage, sessionStorage, indexedDB,
          `import` (statements and `import(`), eval, Function(, window.parent, window.top,
          parent., top., opener, and any http(s):// address but the http://www.w3.org/
          namespaces; in `css`, @import and url() of an http(s) address. `code` and `css`
          at most 64 KB together. Never write data into the code: an array literal of more
          than 12 numbers is refused, and a judge reviews the code with a sample of the
          inputs. A failing review refuses the widget with its findings; warnings are kept
          as its `verdict`. What goes wrong when it draws is kept as its `render_error`:
          check with `get_widget`, fix with `update_widget`.
          Bars of `value` by `region`, with "libraries": ["d3"]:
          export default function render(root, data, ada) {
            const d3 = ada.libraries.d3;
            const rows = data.main.rows;
            const { width, height } = ada.size;
            const m = { top: 8, right: 8, bottom: 24, left: 56 };
            const x = d3.scaleBand(rows.map((r) => r.region), [m.left, width - m.right])
              .padding(0.2);
            const y = d3.scaleLinear([0, d3.max(rows, (r) => r.value)],
              [height - m.bottom, m.top]).nice();
            const svg = d3.select(root).append("svg")
              .attr("width", width).attr("height", height);
            svg.append("g").attr("transform", `translate(0,${height - m.bottom})`)
              .call(d3.axisBottom(x));
            svg.append("g").attr("transform", `translate(${m.left},0)`)
              .call(d3.axisLeft(y).tickFormat((v) => ada.format.number(v)));
            svg.selectAll("rect").data(rows).join("rect")
              .attr("x", (r) => x(r.region)).attr("y", (r) => y(r.value))
              .attr("width", x.bandwidth()).attr("height", (r) => y(0) - y(r.value))
              .attr("fill", ada.colors.series[0])
              .append("title").text((r) => `${r.region}: ${ada.format.number(r.value)}`);
          }

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
        together in reports. Only types that show several datasets read them (a custom
        widget as `data.inputs`); the others ignore them.

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
        it to fix a chart or add labels instead of creating a second widget. A new spec,
        type or inputs clears `render_error`, and a custom widget's code is reviewed again.
        The widget's operator cannot change: for other data, create a widget. A copy on a
        dashboard or in a report version is a widget of its own (its id is in the
        dashboard's slots or the version's blocks) and does not change with the original.
        Returns the widget and its `url`."""
        widget = await widgets.update(
            widget_id, title=title, note=note, type=type, spec=spec, inputs=inputs
        )
        return WidgetView(widget=widget, url=widget_url(widget))

    @mcp.tool
    @inject
    async def get_widget(
        session_id: SessionId, widget_id: Id, widgets: FromDishka[WidgetService]
    ) -> WidgetView:
        """Read one widget with its url: its type, spec (a custom widget's code), inputs,
        `render_error` (what went wrong the last time it was drawn in ADA, null when it
        drew) and `verdict` (the judge's review of a custom widget's code: its outcome and
        findings). After creating or changing a custom widget, check here that it drew,
        then fix it with `update_widget`. A widget is drawn when someone has it open, so a
        new one may show no error yet."""
        widget = await widgets.get(widget_id)
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
