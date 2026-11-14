from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.attachments import Attachment, AttachmentKind
from ada.core.models.base import Id
from ada.core.services.ports.attachments import AttachmentService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["sessions"])


class NewAttachment(Request):
    kind: AttachmentKind
    # The thing's id; for a report a version id, or a report id for its latest version;
    # for a web page its http(s) URL.
    ref: str
    # A web page's title; other things are titled by their name.
    title: str | None = None


@router.get("/sessions/{session_id}/attachments")
async def list_attachments(
    session_id: Id, service: FromDishka[AttachmentService]
) -> Sequence[Attachment]:
    """What the session shows beside its conversation, oldest first."""
    return await service.list(session_id)


@router.post("/sessions/{session_id}/attachments", status_code=status.HTTP_201_CREATED)
async def attach(
    session_id: Id, body: NewAttachment, service: FromDishka[AttachmentService]
) -> Attachment:
    """Attach a thing of the session's project, or a web page. Attaching what is attached
    already answers with the attachment as it is."""
    return await service.attach(session_id, body.kind, body.ref, WEB, body.title)


@router.delete(
    "/sessions/{session_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach(session_id: Id, attachment_id: Id, service: FromDishka[AttachmentService]) -> None:
    await service.detach(session_id, attachment_id, WEB)
