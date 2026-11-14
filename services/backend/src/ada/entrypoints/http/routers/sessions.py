from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status
from pydantic import model_validator

from ada.core.models.agents import PostedMessage
from ada.core.models.base import Id
from ada.core.models.sessions import Context, Session, SessionEntry
from ada.core.models.widgets import Widget
from ada.core.services.ports.agents import AgentTurnService, ResearchService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["sessions"])


class NewSession(Request):
    title: str
    origin_dashboard_id: Id | None = None


class SessionChange(Request):
    """Rename, or put a dashboard in the panel, or both. `panel_dashboard_id` set to null
    clears the panel; leaving it out keeps it."""

    expected_revision: int
    title: str | None = None
    panel_dashboard_id: Id | None = None

    @model_validator(mode="after")
    def _changes_something(self) -> SessionChange:
        if self.title is None and "panel_dashboard_id" not in self.model_fields_set:
            raise ValueError("Give a title or a panel_dashboard_id")
        return self


class NewMessage(Request):
    text: str
    # What the message is about: a pipeline, a dashboard and slot, a widget.
    context: tuple[Context, ...] = ()
    # Another configured model than the session agent, by its id.
    model: str | None = None


class NewResearch(Request):
    # What the research agent should find.
    brief: str
    # The research session's title.
    title: str


@router.get("/projects/{project_id}/sessions")
async def list_sessions(
    project_id: Id, projects: FromDishka[ProjectService], service: FromDishka[SessionService]
) -> Sequence[Session]:
    await projects.get(project_id)
    return await service.list(project_id)


@router.post("/projects/{project_id}/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    project_id: Id, body: NewSession, service: FromDishka[SessionService]
) -> Session:
    return await service.create(project_id, body.title, body.origin_dashboard_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: Id, service: FromDishka[SessionService]) -> Session:
    return await service.get(session_id)


@router.patch("/sessions/{session_id}")
async def change_session(
    session_id: Id, body: SessionChange, service: FromDishka[SessionService]
) -> Session:
    revision = body.expected_revision
    if body.title is not None:
        session = await service.rename(session_id, body.title, revision)
        revision = session.revision
    if "panel_dashboard_id" in body.model_fields_set:
        session = await service.show_dashboard(session_id, body.panel_dashboard_id, revision)
    return session


@router.get("/sessions/{session_id}/entries")
async def list_entries(
    session_id: Id, service: FromDishka[SessionService]
) -> Sequence[SessionEntry]:
    return await service.entries(session_id)


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_message(
    session_id: Id, body: NewMessage, service: FromDishka[AgentTurnService]
) -> PostedMessage:
    """Add a message. With a session agent configured, its answer is queued as a turn,
    which the response carries; `turn` is null without one."""
    return await service.post_message(session_id, body.text, WEB, body.context, body.model)


@router.post("/sessions/{session_id}/research", status_code=status.HTTP_201_CREATED)
async def delegate_research(
    session_id: Id, body: NewResearch, service: FromDishka[ResearchService]
) -> Session:
    """Delegate research to the research agent, as the person: a research session under
    this one, with the brief as its first message and its turn queued. Its report is added
    to this session's record; it does not start a turn here."""
    return await service.delegate(session_id, body.brief, body.title, WEB)


@router.get("/sessions/{session_id}/widgets")
async def list_session_widgets(
    session_id: Id, service: FromDishka[WidgetService]
) -> Sequence[Widget]:
    return await service.list_by_session(session_id)
