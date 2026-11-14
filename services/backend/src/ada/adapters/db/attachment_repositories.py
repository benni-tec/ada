"""What is attached to sessions: only added and removed, never changed."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import dump, fetch, oldest_first, require, rows
from ada.adapters.db.tables import SessionAttachmentRow, SessionRow
from ada.core.models.actors import Actor
from ada.core.models.attachments import Attachment, AttachmentKind
from ada.core.models.base import Id
from ada.core.models.errors import NotFound
from ada.core.ports.repositories import AttachmentRepository

KIND = "attachment"


def _attachment(row: SessionAttachmentRow) -> Attachment:
    return Attachment(
        id=row.id,
        session_id=row.session_id,
        kind=AttachmentKind(row.kind),
        ref=row.ref,
        title=row.title,
        actor=Actor.model_validate(row.actor),
        created_at=row.created_at,
    )


class SqlAttachmentRepository(AttachmentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> Attachment:
        return _attachment(await fetch(self.session, SessionAttachmentRow, id, KIND))

    async def list(self, session_id: Id) -> Sequence[Attachment]:
        statement = oldest_first(
            SessionAttachmentRow, SessionAttachmentRow.session_id == session_id
        )
        return [_attachment(row) for row in await rows(self.session, statement)]

    async def add(self, attachment: Attachment) -> Attachment:
        await require(self.session, SessionRow, attachment.session_id, "session")
        # A session has each thing once, so a second add (or a concurrent one) keeps what
        # was stored first.
        await self.session.execute(
            insert(SessionAttachmentRow)
            .values(
                id=attachment.id,
                session_id=attachment.session_id,
                kind=attachment.kind.value,
                ref=attachment.ref,
                title=attachment.title,
                actor=dump(attachment.actor),
                created_at=attachment.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_session_attachments_ref")
        )
        stored = await rows(
            self.session,
            select(SessionAttachmentRow).where(
                SessionAttachmentRow.session_id == attachment.session_id,
                SessionAttachmentRow.kind == attachment.kind.value,
                SessionAttachmentRow.ref == attachment.ref,
            ),
        )
        return _attachment(stored[0])

    async def remove(self, id: Id) -> None:
        result = await self.session.execute(
            delete(SessionAttachmentRow).where(SessionAttachmentRow.id == id)
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFound(KIND, id)

    async def sessions_with(self, kind: AttachmentKind, ref: str) -> Sequence[Id]:
        statement = oldest_first(
            SessionAttachmentRow,
            SessionAttachmentRow.kind == kind.value,
            SessionAttachmentRow.ref == ref,
        )
        return [row.session_id for row in await rows(self.session, statement)]
