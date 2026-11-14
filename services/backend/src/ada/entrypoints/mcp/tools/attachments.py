from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.attachments import Attachment, AttachmentKind
from ada.core.models.base import DomainModel, Id
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId


class AttachmentState(DomainModel):
    attachment: Attachment
    # The session's page, where the attachment is a tab beside the conversation.
    url: str


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def attach_to_session(
        session_id: SessionId,
        kind: AttachmentKind,
        ref: str,
        attachments: FromDishka[AttachmentService],
        sessions: FromDishka[SessionService],
        title: str | None = None,
    ) -> AttachmentState:
        """Show something beside the conversation in a session, as a tab the person can
        open while you talk. By `kind`, with `ref`:

        - "dashboard" (its id): the dashboard's grid, live, changing as it is edited.
        - "report" (a version id, or a report id for its latest version): that version,
          frozen at its run.
        - "alert_rule" (its id): the rule and its alerts. While attached, each alert of it
          that starts or ends is also recorded in the session.
        - "source" (its id): the data source's provenance, freshness and a preview of rows.
        - "operator" (an operator id): that pipeline's graph and a preview of its rows.
        - "session" (its id): another session of the project, its record read only.
        - "widget" (its id): a widget made elsewhere, e.g. a dashboard's, at the session's
          run.
        - "web_page" (an http or https URL): a link to the page, titled `title` or by its
          host; pages are not shown inside ADA, the person opens them.

        Everything but a web page must be in the session's project. The dashboards and
        reports you create are attached for you. Attaching what is attached already
        returns it unchanged. Returns the attachment and the session's `url`."""
        attachment = await attachments.attach(session_id, kind, ref, calling_agent(), title)
        session = await sessions.get(session_id)
        return AttachmentState(
            attachment=attachment,
            url=f"/projects/{session.project_id}/sessions/{session.id}",
        )

    @mcp.tool
    @inject
    async def detach_from_session(
        session_id: SessionId, attachment_id: Id, attachments: FromDishka[AttachmentService]
    ) -> Sequence[Attachment]:
        """Take an attachment away from beside the conversation, e.g. a dashboard the
        person no longer needs to see, by the attachment's id as `attach_to_session`
        returned it. The thing itself stays as it is. Returns the session's remaining
        attachments."""
        await attachments.detach(session_id, attachment_id, calling_agent())
        return await attachments.list(session_id)
