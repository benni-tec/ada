from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.attachments import Attachment, AttachmentKind
from ada.core.models.base import Id


class AttachmentService(Protocol):
    """What is shown beside a session, one tab per thing, and listed to its agent."""

    async def attach(
        self,
        session_id: Id,
        kind: AttachmentKind,
        ref: str,
        actor: Actor,
        title: str | None = None,
    ) -> Attachment:
        """Attach a thing of the session's project (NotFound when it does not exist,
        Invalid when it is another project's), or a web page by its http(s) URL. For a
        report, `ref` may be the report's id, which attaches its latest version. `title`
        names a web page (its host by default); other things are titled by their name.
        Attaching what is attached already returns the attachment as it is."""
        ...

    async def attach_report_version(
        self, session_id: Id, version_id: Id, actor: Actor
    ) -> Attachment:
        """Attach a new version of a report in place of the versions of the same report
        attached before."""
        ...

    async def detach(self, session_id: Id, attachment_id: Id, actor: Actor) -> None: ...

    async def list(self, session_id: Id) -> Sequence[Attachment]:
        """Oldest first."""
        ...
