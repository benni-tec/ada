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


class UnitsOfWork(Protocol):
    """Runs a use case in a unit of work of its own: for an action after a commit, whose
    own unit of work has ended, or one that must not wait for a long-running one."""

    async def run[S](self, service: type[S], work: Callable[[S], Awaitable[None]]) -> None:
        """Resolve `service` in a new unit of work and call `work` with it. It commits when
        `work` returns and rolls back when it raises, raising on."""
        ...
