from collections.abc import Sequence
from urllib.parse import urlsplit
from uuid import UUID, uuid7

from ada.core.models.actors import Actor
from ada.core.models.attachments import MAX_URL, Attachment, AttachmentKind
from ada.core.models.base import Id
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.events import Event, EventType
from ada.core.models.reports import ReportVersion
from ada.core.models.sessions import Session
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    AlertRuleRepository,
    AttachmentRepository,
    DashboardRepository,
    DataSourceRepository,
    OperatorRepository,
    ReportRepository,
    SessionRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.pipelines.listing import name as operator_name
from ada.core.services.ports.attachments import AttachmentService

# How each kind is named in messages.
LABELS = {
    AttachmentKind.DASHBOARD: "dashboard",
    AttachmentKind.REPORT: "report",
    AttachmentKind.ALERT_RULE: "alert rule",
    AttachmentKind.SOURCE: "data source",
    AttachmentKind.OPERATOR: "pipeline",
    AttachmentKind.SESSION: "session",
    AttachmentKind.WIDGET: "widget",
    AttachmentKind.WEB_PAGE: "web page",
}


class Attachments(AttachmentService):
    """Attaches only what the session's project has, so a tab never shows another
    project's work, and announces every change to the session's viewers."""

    def __init__(
        self,
        attachments: AttachmentRepository,
        sessions: SessionRepository,
        dashboards: DashboardRepository,
        reports: ReportRepository,
        rules: AlertRuleRepository,
        data_sources: DataSourceRepository,
        operators: OperatorRepository,
        widgets: WidgetRepository,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.attachments = attachments
        self.sessions = sessions
        self.dashboards = dashboards
        self.reports = reports
        self.rules = rules
        self.data_sources = data_sources
        self.operators = operators
        self.widgets = widgets
        self.events = events
        self.clock = clock

    async def attach(
        self,
        session_id: Id,
        kind: AttachmentKind,
        ref: str,
        actor: Actor,
        title: str | None = None,
    ) -> Attachment:
        session = await self.sessions.get(session_id)
        ref, name = await self._resolve(session, kind, ref.strip())
        if kind is AttachmentKind.WEB_PAGE and title is not None and title.strip():
            name = title.strip()
        attachment = Attachment(
            id=uuid7(),
            session_id=session.id,
            kind=kind,
            ref=ref,
            title=name,
            actor=actor,
            created_at=self.clock.now(),
        )
        stored = await self.attachments.add(attachment)
        if stored.id == attachment.id:
            await self._publish(session, EventType.SESSION_ATTACHMENT_ADDED, stored)
        return stored

    async def attach_report_version(
        self, session_id: Id, version_id: Id, actor: Actor
    ) -> Attachment:
        attached = await self.attach(session_id, AttachmentKind.REPORT, str(version_id), actor)
        version = await self.reports.get_version(version_id)
        session = await self.sessions.get(session_id)
        for other in await self.attachments.list(session_id):
            if other.kind is not AttachmentKind.REPORT or other.id == attached.id:
                continue
            try:
                earlier = await self.reports.get_version(UUID(other.ref))
            except NotFound:
                continue
            if earlier.report_id == version.report_id:
                await self._remove(session, other)
        return attached

    async def detach(self, session_id: Id, attachment_id: Id, actor: Actor) -> None:
        session = await self.sessions.get(session_id)
        attachment = await self.attachments.get(attachment_id)
        if attachment.session_id != session.id:
            # Another session's attachment is not one of this session's.
            raise NotFound("attachment", attachment_id)
        await self._remove(session, attachment)

    async def list(self, session_id: Id) -> Sequence[Attachment]:
        # Read the session first, so an unknown id is a 404 and not an empty list.
        await self.sessions.get(session_id)
        return await self.attachments.list(session_id)

    async def _resolve(self, session: Session, kind: AttachmentKind, ref: str) -> tuple[str, str]:
        """The ref to store and the thing's name. Raises NotFound for a thing that does not
        exist and Invalid for one the session cannot show."""
        label = LABELS[kind]
        if kind is AttachmentKind.WEB_PAGE:
            return ref, _host(ref)
        if kind is AttachmentKind.OPERATOR:
            operator = await self.operators.get(ref)
            _same_project(session, operator.project_id, label)
            names = {s.id: s.name for s in await self.data_sources.list(operator.project_id)}
            return operator.id, operator_name(operator, names)
        id = _id(ref, label)
        match kind:
            case AttachmentKind.DASHBOARD:
                dashboard = await self.dashboards.get(id)
                project_id, name = dashboard.project_id, dashboard.name
            case AttachmentKind.REPORT:
                version = await self._report_version(id)
                report = await self.reports.get(version.report_id)
                id, project_id = version.id, report.project_id
                name = f"{report.name} {version.version}"
            case AttachmentKind.ALERT_RULE:
                rule = await self.rules.get(id)
                project_id, name = rule.project_id, rule.name
            case AttachmentKind.SOURCE:
                source = await self.data_sources.get(id)
                project_id, name = source.project_id, source.name
            case AttachmentKind.SESSION:
                if id == session.id:
                    raise Invalid("A session cannot be attached to itself")
                other = await self.sessions.get(id)
                project_id, name = other.project_id, other.title
            case AttachmentKind.WIDGET:
                widget = await self.widgets.get(id)
                project_id, name = widget.project_id, widget.title
        _same_project(session, project_id, label)
        return str(id), name

    async def _report_version(self, id: Id) -> ReportVersion:
        """The version of that id, or else the latest version of the report of that id."""
        try:
            return await self.reports.get_version(id)
        except NotFound:
            report = await self.reports.get(id)
        if report.latest_version_id is None:
            raise Invalid(f"The report {report.id} has no version to show yet")
        return await self.reports.get_version(report.latest_version_id)

    async def _remove(self, session: Session, attachment: Attachment) -> None:
        await self.attachments.remove(attachment.id)
        await self._publish(session, EventType.SESSION_ATTACHMENT_REMOVED, attachment)

    async def _publish(self, session: Session, type: EventType, attachment: Attachment) -> None:
        await self.events.publish(
            Event(
                type=type,
                project_id=session.project_id,
                payload={
                    "session_id": str(session.id),
                    "attachment_id": str(attachment.id),
                    "attachment": attachment.model_dump(mode="json"),
                },
                at=self.clock.now(),
            )
        )


def _id(ref: str, label: str) -> Id:
    try:
        return UUID(ref)
    except ValueError:
        raise Invalid(f"A {label} is attached by its id; {ref!r} is not an id") from None


def _same_project(session: Session, project_id: Id, label: str) -> None:
    if project_id != session.project_id:
        raise Invalid(f"The {label} belongs to another project than the session")


def _host(url: str) -> str:
    """The host of a web page's http(s) URL, which titles the page unless it is given a
    title. Raises Invalid for anything else."""
    if len(url) > MAX_URL:
        raise Invalid(f"A web page's URL may be at most {MAX_URL:,} characters")
    try:
        parts = urlsplit(url)
        scheme, host = parts.scheme, parts.hostname
    except ValueError:  # e.g. an unclosed IPv6 bracket
        scheme, host = "", None
    if scheme not in ("http", "https") or not host or any(c.isspace() for c in url):
        raise Invalid(f"A web page is attached by its http(s) URL, not {url!r}")
    return host
