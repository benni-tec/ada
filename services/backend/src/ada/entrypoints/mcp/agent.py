"""The in-platform agent's tools: the MCP server create_mcp builds, called in process
through FastMCP's in-memory client, so the agent can do exactly what an external agent can
and every call is a unit of work of its own, as over HTTP."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from dishka import AsyncContainer, Scope
from fastmcp import Client
from mcp.types import Implementation, TextContent

from ada.core.models.actors import Actor
from ada.core.models.agents import ToolSpec
from ada.core.models.base import Id, JsonObject
from ada.core.models.sessions import SessionAgent
from ada.core.ports.agents import AgentToolbox, AgentTools, ToolCallFailed
from ada.entrypoints.mcp.actor import acting_as
from ada.entrypoints.mcp.server import create_mcp

# Tools that make no sense inside a session the agent already works in: the widget's own
# data call, and creating projects or sessions.
LEFT_OUT = frozenset({"get_widget_data", "create_project", "create_session"})

# The research agent works with these only: it looks for data and adds it as sources, then
# reports back. Dashboards, reports and alerts are the session agent's.
RESEARCH_TOOLS = frozenset(
    {
        "search_web",
        "read_page",
        "extract_table",
        "map_site",
        "register_source",
        "refresh_source",
        "list_sources",
        "update_source",
        "add_source_operator",
        "preview_operator",
        "watch_source",
        "watch_sources",
        "report_back",
    }
)
# The analyst works on the project's data with these, and reports findings. It adds no
# sources and builds no widgets: whoever delegated shows what it found.
ANALYSIS_TOOLS = frozenset(
    {
        "list_pipelines",
        "get_lineage",
        "list_sources",
        "add_source_operator",
        "preview_operator",
        "query_operator",
        "add_transform",
        "add_statistic",
        "report_findings",
    }
)
# Only a delegated session reports back.
CHILD_ONLY = frozenset({"report_back", "report_findings"})

# Only for the server's logs: the actor comes from acting_as, never from this name.
CLIENT = Implementation(name="ada-in-platform-agent", version="1")


class InProcessToolbox(AgentToolbox):
    def __init__(self, container: AsyncContainer) -> None:
        # The application's container: each tool call opens its own request scope from it.
        self.container = application(container)

    @asynccontextmanager
    async def connect(
        self, agent: Actor, session_id: Id, profile: SessionAgent = SessionAgent.SESSION
    ) -> AsyncIterator[AgentTools]:
        # Set before the client starts the in-memory server, whose tasks copy the context.
        with acting_as(agent):
            async with Client(create_mcp(self.container), client_info=CLIENT) as client:
                listed = await client.list_tools()
                specs = [
                    ToolSpec(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=_session_optional(tool.input_schema),
                    )
                    for tool in listed
                    if _offered(tool.name, profile)
                ]
                yield _McpTools(client, specs, session_id, profile is not SessionAgent.SESSION)


def _session_optional(schema: JsonObject) -> JsonObject:
    """A tool's schema as the model sees it: `session_id` may be left out, since every call
    is filled in with the turn's session (see _McpTools.call)."""
    required = schema.get("required")
    if not required or "session_id" not in required:
        return schema
    return {**schema, "required": [name for name in required if name != "session_id"]}


def _offered(name: str, profile: SessionAgent) -> bool:
    if profile is SessionAgent.RESEARCH:
        return name in RESEARCH_TOOLS
    if profile is SessionAgent.ANALYSIS:
        return name in ANALYSIS_TOOLS
    return name not in LEFT_OUT and name not in CHILD_ONLY


def application(container: AsyncContainer) -> AsyncContainer:
    """The APP-scoped container above `container`, e.g. above a worker task's request
    scope. Not the topmost one: above APP is dishka's RUNTIME container, from which a tool
    call would open an APP scope and find none of the request-scoped services."""
    while container.scope is not Scope.APP:
        if container.parent_container is None:
            raise ValueError(f"No application container above {container.scope}")
        container = container.parent_container
    return container


class _McpTools(AgentTools):
    def __init__(
        self, client: Client, specs: Sequence[ToolSpec], session_id: Id, bound: bool
    ) -> None:
        self.client = client
        self._specs = list(specs)
        self.session_id = session_id
        # Whether every call is in the turn's session, whatever the model passes.
        self.bound = bound
        self._by_name = {spec.name: spec for spec in specs}

    def specs(self) -> Sequence[ToolSpec]:
        return self._specs

    async def call(self, name: str, arguments: JsonObject) -> Any:
        spec = self._by_name.get(name)
        if spec is None:
            raise ToolCallFailed(f"There is no tool {name!r}")
        arguments = dict(arguments)
        # The turn's session, when the model leaves it out: its work belongs there. The
        # research agent works in its own session only, so it cannot spend its parent's.
        if "session_id" in spec.input_schema.get("properties", {}) and (
            self.bound or not arguments.get("session_id")
        ):
            arguments["session_id"] = str(self.session_id)
        result = await self.client.call_tool(name, arguments, raise_on_error=False)
        if result.is_error:
            raise ToolCallFailed(_text(result.content) or f"{name} failed")
        content = result.structured_content
        if content is None:
            return _text(result.content)
        # Lists come wrapped, since structured content must be an object.
        return content["result"] if set(content) == {"result"} else content


def _text(content: Sequence[Any]) -> str:
    return "\n".join(item.text for item in content if isinstance(item, TextContent))
