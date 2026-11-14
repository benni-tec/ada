"""The widget bundles as MCP App resources (the MCP Apps extension, io.modelcontextprotocol/ui).

Every built bundle in WIDGETS_DIR is a resource `ui://ada/widgets/<type>.html`. create_widget
names `ui://ada/widgets/any.html`, the bundle that renders every type, so a host that
supports MCP Apps shows the widget right after the call. Inside the host the widget gets
its data through the get_widget_data tool, not REST (services/widgets/src/lib/host.ts).
"""

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.resources import FileResource

# The bundle create_widget is rendered with: it picks the widget type at run time.
ANY_WIDGET = "ui://ada/widgets/any.html"


def bundle_uri(type: str) -> str:
    return f"ui://ada/widgets/{type}.html"


def register_widget_bundles(mcp: FastMCP, widgets_dir: Path) -> None:
    """One resource per built bundle. Read from disk on every read, so a rebuild needs no
    restart. Without a build there is nothing to serve, and the tools work as before."""
    if not widgets_dir.is_dir():
        return
    for path in sorted(widgets_dir.glob("*.html")):
        mcp.add_resource(
            FileResource(
                uri=bundle_uri(path.stem),
                path=path.resolve(),
                name=f"{path.stem} widget",
                description=f"Renders a widget of type {path.stem!r}"
                if path.stem != "any"
                else "Renders a widget of any type",
                mime_type="text/html;profile=mcp-app",
            )
        )
