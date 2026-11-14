from collections.abc import Awaitable, Callable
from typing import Any

from dishka import AsyncContainer
from dishka.integrations.base import wrap_injection

type Inject = Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]


def make_inject(container: AsyncContainer) -> Inject:
    """dishka has no FastMCP integration; this is its `@inject` for tools.

    Each tool call runs in its own REQUEST scope, like an HTTP request. The FromDishka
    parameters are removed from the signature, so FastMCP's tool schema only shows the real
    arguments. The container comes from create_mcp rather than the HTTP request: tool calls
    do not run in the request's task, and in-memory clients have no request at all.
    """

    def inject[F: Callable[..., Awaitable[Any]]](func: F) -> F:
        return wrap_injection(
            func=func,
            container_getter=lambda args, kwargs: container,
            is_async=True,
            manage_scope=True,
        )

    return inject
