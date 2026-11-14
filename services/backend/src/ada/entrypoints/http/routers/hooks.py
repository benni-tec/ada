"""Webhooks that outside services call. Public: each delivery proves itself by its signature."""

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Header, HTTPException, Request, status

from ada.core.models.base import DomainModel, Id
from ada.core.models.errors import NotFound
from ada.core.ports.system import Clock
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.transactions import AfterCommit
from ada.core.services.ports.sources import SourceService

router = APIRouter(route_class=DishkaRoute, tags=["hooks"])


class HookQueued(DomainModel):
    status: str = "queued"


@router.post("/hooks/context/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def context_monitor_fired(
    source_id: Id,
    request: Request,
    service: FromDishka[SourceService],
    dispatcher: FromDishka[TaskDispatcher],
    after_commit: FromDishka[AfterCommit],
    clock: FromDishka[Clock],
    x_context_signature: str | None = Header(default=None),
) -> HookQueued:
    """A Context.dev monitor saw its page change: refresh the source. Only the headers and
    the signature are used; nothing in the body is trusted or read."""
    source = await service.get(source_id)
    if source.monitor_id is None:
        raise NotFound("monitor of data source", source_id)
    body = await request.body()
    if not await service.verify_push(source_id, body, x_context_signature, clock.now()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The signature does not match")
    after_commit.add(lambda: dispatcher.refresh_source(source_id, True))
    return HookQueued()
