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
- Present results only through widgets (in a session or on a dashboard) and reports, so \
every number the person sees can be traced to its pipeline.
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
