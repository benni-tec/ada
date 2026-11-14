from fastmcp.server.dependencies import get_context

from ada.core.models.actors import Actor, ActorKind

UNKNOWN_CLIENT = "unknown client"


def calling_agent() -> Actor:
    """Who is calling the tool: an external agent, named after the MCP client it connected
    with (the client info of the initialize handshake, e.g. "claude-code").

    FastMCP has no helper for this; the name sits on `client_info` of the session's
    `client_params`, which is None when the client sent none. Without a name the actor is
    still recorded, so the session shows that an agent acted, just not which.
    """
    return Actor(kind=ActorKind.EXTERNAL_AGENT, name=_client_name() or UNKNOWN_CLIENT)


def _client_name() -> str | None:
    try:
        params = get_context().session.client_params
    except RuntimeError:
        # Outside a request there is no context, and so no client.
        return None
    if params is None or params.client_info is None:
        return None
    return params.client_info.name.strip() or None
