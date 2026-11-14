"""Every ADA tool call works in a session, and the session shows each call."""

import logging
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

import mcp.types as mt
from dishka import AsyncContainer
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.addressing import parse_hashed_backend_name
from fastmcp.tools import ToolResult
from pydantic import Field

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.sessions import ToolCall, ToolCallStatus
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.actor import calling_agent, in_platform_agent
from ada.entrypoints.mcp.injection import tool_errors

logger = logging.getLogger(__name__)

# The tools that work outside any session: finding or making a project and a session to
# work in, the platform's health, and the widget's own data call (MCP Apps visibility
# "app"), which a widget makes, not an agent.
SESSIONLESS = frozenset(
    {"list_projects", "create_project", "create_session", "system_status", "get_widget_data"}
)

# Every other tool's `session_id`: required, and what its schema says about it.
SessionId = Annotated[
    Id,
    Field(
        description="The session this call works in (create_session gives one); it shows the "
        "call, and what the call makes, to the people following the work."
    ),
]

NO_SESSION = (
    "Pass `session_id`: every ADA tool works in a session, which shows each call to the "
    "people following the work. Start one with create_session."
)


class SessionToolCalls(Middleware):
    """Checks the session of every tool call but the SESSIONLESS ones, and records each
    external agent's call as a `tool_call` entry of that session.

    The check runs before the call: the session must exist, and be in the call's
    `project_id` if it names one. The entry is written after the call in a unit of work of
    its own, so a failed call is recorded too while its own writes are rolled back, and
    `session.entry_added` is published once that entry is committed. The in-platform agent's
    calls are not recorded: its turn already shows each one.
    """

    def __init__(self, container: AsyncContainer) -> None:
        # The application's container: the check and the entry each open a request scope.
        self.container = container

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = _local_name(context.message.name)
        if tool in SESSIONLESS:
            return await call_next(context)
        arguments = context.message.arguments or {}
        if not arguments.get("session_id"):
            raise ToolError(NO_SESSION)
        session_id = _uuid(arguments["session_id"])
        if session_id is None:
            # Not an id: the tool's own argument check says so.
            return await call_next(context)
        await self._check(session_id, _uuid(arguments.get("project_id")))
        if in_platform_agent():
            return await call_next(context)

        actor = calling_agent()
        started = perf_counter()
        try:
            result = await call_next(context)
        except Exception as error:
            await self._record(session_id, tool, arguments, actor, started, error)
            raise
        await self._record(session_id, tool, arguments, actor, started, None)
        return result

    async def _check(self, session_id: UUID, project_id: UUID | None) -> None:
        with tool_errors():
            async with self.container() as request:
                sessions = await request.get(SessionService)
                await sessions.check(session_id, project_id)

    async def _record(
        self,
        session_id: UUID,
        tool: str,
        arguments: dict[str, Any],
        actor: Actor,
        started: float,
        error: Exception | None,
    ) -> None:
        call = ToolCall(
            tool=tool,
            arguments=arguments,
            status=ToolCallStatus.OK if error is None else ToolCallStatus.ERROR,
            error=None if error is None else (str(error) or type(error).__name__),
            duration_ms=round((perf_counter() - started) * 1000),
        )
        try:
            async with self.container() as request:
                sessions = await request.get(SessionService)
                await sessions.record_tool_call(session_id, call, actor)
        except Exception:
            # The call itself went as it went; a record that could not be written must not
            # hide its answer or its error.
            logger.exception("The tool call %s could not be recorded", tool)


def _local_name(name: str) -> str:
    # A widget calls its app-visible tools under a hashed name: "__<hash>_get_widget_data".
    hashed = parse_hashed_backend_name(name)
    return hashed[1] if hashed is not None else name


def _uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value)) if value is not None else None
    except ValueError:
        return None
