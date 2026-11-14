from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from dishka import AsyncContainer
from dishka.integrations.base import wrap_injection
from fastmcp.exceptions import ToolError

from ada.core.models.errors import Conflict, Invalid, NotConfigured, NotFound, Unavailable

type Inject = Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]


@contextmanager
def tool_errors() -> Iterator[None]:
    """The core's errors as tool errors with a readable message. Use it outside the scope
    whose transaction they should roll back."""
    try:
        yield
    except Unavailable as error:
        raise ToolError(f"{error}. This is temporary; try again later.") from error
    except (NotFound, Conflict, Invalid, NotConfigured) as error:
        raise ToolError(str(error)) from error


def make_inject(container: AsyncContainer) -> Inject:
    """dishka has no FastMCP integration; this is its `@inject` for tools.

    Each tool call runs in its own REQUEST scope, like an HTTP request. The FromDishka
    parameters are removed from the signature, so FastMCP's tool schema only shows the real
    arguments. The container comes from create_mcp rather than the HTTP request: tool calls
    do not run in the request's task, and in-memory clients have no request at all.

    The core's errors are reported to the agent as tool errors with a readable message, after
    they have passed through the scope, so the call's transaction rolls back first.
    """

    def inject[F: Callable[..., Awaitable[Any]]](func: F) -> F:
        injected = wrap_injection(
            func=func,
            container_getter=lambda args, kwargs: container,
            is_async=True,
            manage_scope=True,
        )

        async def reported(*args: Any, **kwargs: Any) -> Any:
            with tool_errors():
                return await injected(*args, **kwargs)

        # FastMCP builds the tool's schema from these: the injected function's, which no
        # longer list the FromDishka parameters. functools.wraps would carry the original
        # function's annotations along.
        for name in ("__name__", "__qualname__", "__doc__", "__module__", "__signature__"):
            setattr(reported, name, getattr(injected, name))
        reported.__annotations__ = injected.__annotations__
        return reported  # type: ignore[return-value]

    return inject
