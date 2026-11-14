from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from fastmcp.server.dependencies import get_context

from ada.core.models.actors import Actor, ActorKind

UNKNOWN_CLIENT = "unknown client"

# Set only by the in-platform agent's in-process client (ada.entrypoints.mcp.agent), in the
# worker's own task, from which the in-memory server's tasks inherit it. A client over HTTP
# runs in tasks of the HTTP server that never see it, so whatever name it reports, it is an
# external agent.
_in_platform_agent: ContextVar[Actor | None] = ContextVar("in_platform_agent", default=None)


def calling_agent() -> Actor:
    """Who is calling the tool: the in-platform agent, named after its model, or else an
    external agent, named after the MCP client it connected with (the client info of the
    initialize handshake, e.g. "claude-code").

    FastMCP has no helper for this; the name sits on `client_info` of the session's
    `client_params`, which is None when the client sent none. Without a name the actor is
    still recorded, so the session shows that an agent acted, just not which.
    """
    if (agent := _in_platform_agent.get()) is not None:
        return agent
    return Actor(kind=ActorKind.EXTERNAL_AGENT, name=_client_name() or UNKNOWN_CLIENT)


@contextmanager
def acting_as(agent: Actor) -> Iterator[None]:
    """Tool calls made from inside this block, including those of servers and clients
    started inside it, act as `agent`."""
    token = _in_platform_agent.set(agent)
    try:
        yield
    finally:
        _in_platform_agent.reset(token)


def _client_name() -> str | None:
    try:
        params = get_context().session.client_params
    except RuntimeError:
        # Outside a request there is no context, and so no client.
        return None
    if params is None or params.client_info is None:
        return None
    return params.client_info.name.strip() or None
