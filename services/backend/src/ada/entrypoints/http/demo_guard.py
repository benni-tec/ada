import re
from uuid import UUID

from dishka import AsyncContainer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ada.core.ports.system import ProjectOwners

WRITES = {"POST", "PUT", "PATCH", "DELETE"}
UUIDS = re.compile(r"[0-9a-fA-F]{8}-?(?:[0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}")
# Demo projects are view-only for visitors: no chat either, since the agent can change them.
# What-if evaluations, runs and webhooks stay open.
ALLOWED = re.compile(
    r"/api/(?:"
    r"projects/[^/]+/runs"
    r"|dashboards/[^/]+/runs"
    r"|models/[^/]+/evaluate"
    r"|case-types/[^/]+/cases/[^/]+/evaluate"
    r"|hooks/.*"
    r")/?"
)
REFUSAL = {"detail": "Demo projects are view-only: create your own project to try the agent."}


class DemoGuard:
    """Refuses a visitor's change to one of the team's demo projects. The gateway marks a
    visitor's request with X-Ada-Visitor: 1 and strips the header from the team's."""

    def __init__(self, app: ASGIApp, container: AsyncContainer, protected: frozenset[UUID]) -> None:
        self.app = app
        self.container = container
        self.protected = protected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and await self._refused(scope):
            await JSONResponse(REFUSAL, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _refused(self, scope: Scope) -> bool:
        path: str = scope["path"]
        if (
            scope["method"] not in WRITES
            or (b"x-ada-visitor", b"1") not in scope["headers"]
            or ALLOWED.fullmatch(path)
        ):
            return False
        ids = {UUID(match) for match in UUIDS.findall(path)}
        if not ids:
            return False
        owners = await self.container.get(ProjectOwners)
        return bool(await owners.of(ids) & self.protected)
