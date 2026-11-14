from collections.abc import AsyncIterator
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from ada.core.ports.events import EventStream

router = APIRouter(route_class=DishkaRoute, tags=["events"])


@router.get("/projects/{project_id}/events", response_class=EventSourceResponse)
async def project_events(
    project_id: UUID, stream: FromDishka[EventStream]
) -> AsyncIterator[ServerSentEvent]:
    """The project's live stream: each message is `event: <type>` and `data: <Event JSON>`.

    FastAPI does the rest of the contract: a `: ping` comment after 15 quiet seconds, so
    proxies keep the connection open, headers that stop proxy buffering (X-Accel-Buffering)
    and caching, and cancelling this generator when the client disconnects, which ends the
    subscription.
    """
    async for event in stream.subscribe(project_id):
        yield ServerSentEvent(event=event.type.value, raw_data=event.model_dump_json())
