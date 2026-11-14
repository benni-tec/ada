from dishka import AsyncContainer
from fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send

from ada.entrypoints.mcp import system
from ada.entrypoints.mcp.injection import make_inject


def create_mcp(container: AsyncContainer) -> FastMCP:
    """MCP server exposing ADA to agents, mounted at /mcp."""
    mcp = FastMCP(
        "ADA",
        instructions=(
            "Tools for traceable data analysis: build pipelines of operators over data "
            "sources, and show their results as widgets on dashboards and in reports."
        ),
    )
    inject = make_inject(container)
    for module in (system,):
        module.register(mcp, inject)
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
