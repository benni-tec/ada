from collections.abc import Sequence
from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Query, status

from ada.core.models.base import Id, JsonObject
from ada.core.models.operators import OperatorId
from ada.core.models.widgets import MAIN_INPUT, Widget, WidgetData
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.limits import MAX_ROWS
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["widgets"])


class NewWidget(Request):
    # A widget is made from an operator id; no data passes through the request.
    operator_id: OperatorId
    type: str
    title: str
    spec: JsonObject | None = None
    note: str = ""
    session_id: Id | None = None
    # Further operators the widget reads, by name; its own is the input "main".
    inputs: dict[str, OperatorId] | None = None


@router.post("/projects/{project_id}/widgets", status_code=status.HTTP_201_CREATED)
async def create_widget(
    project_id: Id,
    body: NewWidget,
    projects: FromDishka[ProjectService],
    service: FromDishka[WidgetService],
) -> Widget:
    await projects.get(project_id)
    return await service.create(
        project_id,
        body.operator_id,
        body.type,
        body.title,
        WEB,
        spec=body.spec,
        note=body.note,
        session_id=body.session_id,
        inputs=body.inputs,
    )


@router.get("/projects/{project_id}/widgets")
async def list_widgets(
    project_id: Id, projects: FromDishka[ProjectService], service: FromDishka[WidgetService]
) -> Sequence[Widget]:
    """Every widget of the project, in a session or not, oldest first."""
    await projects.get(project_id)
    return await service.list(project_id)


@router.get("/widgets/{widget_id}")
async def get_widget(widget_id: Id, service: FromDishka[WidgetService]) -> Widget:
    return await service.get(widget_id)


class WidgetChange(Request):
    """Fields left out stay as they are; a spec or inputs replace the old ones whole."""

    title: str | None = None
    note: str | None = None
    type: str | None = None
    spec: JsonObject | None = None
    inputs: dict[str, OperatorId] | None = None


@router.patch("/widgets/{widget_id}")
async def update_widget(
    widget_id: Id, body: WidgetChange, service: FromDishka[WidgetService]
) -> Widget:
    return await service.update(
        widget_id,
        title=body.title,
        note=body.note,
        type=body.type,
        spec=body.spec,
        inputs=body.inputs,
    )


@router.get("/widgets/{widget_id}/data")
async def get_widget_data(
    widget_id: Id,
    service: FromDishka[WidgetService],
    run_id: Id | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 1000,
    input: str = MAIN_INPUT,
) -> WidgetData:
    """What the widget shows: one input ("main", its own operator, by default). Without
    `run_id` a new run is started, with no bindings and an open time range."""
    return await service.data(widget_id, run_id, limit, input)
