from collections.abc import Awaitable, Callable
from typing import Protocol


class AfterCommit(Protocol):
    """Defers an action until the current unit of work (one HTTP request, MCP tool call or
    worker task) has committed. For whatever another process must only see once the data
    it refers to is stored: events, and tasks that read what this unit of work wrote."""

    def add(self, action: Callable[[], Awaitable[None]]) -> None:
        """Run `action` after the commit, and never when the work rolls back. A failing
        action is logged: the commit has happened and cannot be undone."""
        ...
