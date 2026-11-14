from datetime import datetime
from enum import StrEnum

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id

# A web page's address, at most this long.
MAX_URL = 2048


class AttachmentKind(StrEnum):
    """What can be attached to a session. `ref` is the thing's id, unless said otherwise."""

    DASHBOARD = "dashboard"
    # `ref` is a report *version* id: what the person sees is frozen.
    REPORT = "report"
    ALERT_RULE = "alert_rule"
    SOURCE = "source"
    # A pipeline, by its operator id.
    OPERATOR = "operator"
    # Another session of the project.
    SESSION = "session"
    # A widget from elsewhere: a dashboard's, another session's.
    WIDGET = "widget"
    # `ref` is an http(s) URL, at most MAX_URL characters.
    WEB_PAGE = "web_page"


class Attachment(DomainModel):
    """Something shown beside a session, as a tab, and listed to its agent. A session has
    each thing attached at most once. An attachment is added or removed, never changed."""

    id: Id
    session_id: Id
    kind: AttachmentKind
    ref: str
    # The thing's name when it was attached; for a web page, the title given or its host.
    title: str
    actor: Actor
    created_at: datetime
