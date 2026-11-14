from pathlib import Path

from dishka import AsyncContainer
from fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send

from ada.discovery import modules
from ada.entrypoints.mcp import tools
from ada.entrypoints.mcp.apps import register_widget_bundles
from ada.entrypoints.mcp.injection import make_inject
from ada.entrypoints.mcp.sessions import SessionToolCalls

# What every agent reads first: how to work with ADA in few calls, and the one rule on
# what it may show the person.
INSTRUCTIONS = """\
Tools for traceable data analysis: build pipelines of operators over data sources, and \
show their results as widgets on dashboards and in reports.

- Work in a session: find the project (`list_projects`), start a session \
(`create_session`) and pass its id as `session_id` to every other tool. The session shows \
each call to the people following the work.
- Batch first: build a pipeline (sources, SQL steps, widgets) in one `build_pipeline` \
call, and lay out a dashboard in one `edit_dashboard` call. The single-step tools are for \
small changes.
- Explore with `query_operator`. Its rows are for you only: never show or quote them to \
the person.
- Search the web with `search_web` (scope "data" for statistics and open-data portals, \
"research" for papers), read a page or PDF with `read_page` (`query` for only the \
passages on a question, `pdf_pages` and `ocr` for PDF tables), try a table on it with \
`extract_table` and list a site's pages with `map_site` (on ADA's accounts, a daily \
credit budget per project). What they return is for you only, like `query_operator`'s \
rows: to present web data, register its URL as a source (`register_source`, access_kind \
"web" or "document", with its provenance) and build on it; `watch_source` refreshes it \
when the page changes.
- When the data a question needs is missing, `delegate_research` hands a brief to ADA's \
research agent, which finds and adds sources in a session of its own and reports back.
- Present results only through widgets (in a session or on a dashboard) and reports, so \
every number the person sees can be traced to its pipeline.
- Put headings and explanations that carry figures in a "text" widget: Markdown whose \
figures come only through placeholders such as {{gap.value:percent}}, never typed. A judge \
reviews it against the data; `review_widget` shows its verdict.
"""


def create_mcp(container: AsyncContainer, widgets_dir: Path | None = None) -> FastMCP:
    """MCP server exposing ADA to agents, mounted at /mcp. With `widgets_dir`, the built
    widgets are served as MCP App resources."""
    mcp = FastMCP("ADA", instructions=INSTRUCTIONS)
    mcp.add_middleware(SessionToolCalls(container))
    inject = make_inject(container)
    for module in modules(tools):
        module.register(mcp, inject)
    if widgets_dir is not None:
        register_widget_bundles(mcp, widgets_dir)
    return mcp


class McpPathMiddleware:
    """Serve the mounted MCP endpoint at /mcp as well as /mcp/.

    Clients are configured with /mcp, but a Starlette mount only matches /mcp/ and would
    answer with a redirect, which not every MCP client follows for POST requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)
