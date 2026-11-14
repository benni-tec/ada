from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Query, status

from ada.core.models.analysis import Rows
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.runs import Run
from ada.core.models.time import TimeRange
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.limits import MAX_ROWS
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["runs"])


class NewRun(Request):
    time_range: TimeRange | None = None
    # Input slot name to the operator bound to it; any binding makes the run a scenario.
    bindings: dict[str, OperatorId] | None = None


@router.post("/projects/{project_id}/runs", status_code=status.HTTP_201_CREATED)
async def start_run(
    project_id: Id,
    projects: FromDishka[ProjectService],
    service: FromDishka[RunService],
    body: NewRun | None = None,
) -> Run:
    await projects.get(project_id)
    body = body or NewRun()
    return await service.start(project_id, WEB, body.time_range, body.bindings)


@router.get("/runs/{run_id}")
async def get_run(run_id: Id, service: FromDishka[RunService]) -> Run:
    return await service.get(run_id)


@router.get("/runs/{run_id}/operators/{operator_id}/rows")
async def read_rows(
    run_id: Id,
    operator_id: OperatorId,
    service: FromDishka[RunService],
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 1000,
) -> Rows:
    return await service.read(run_id, operator_id, limit)
