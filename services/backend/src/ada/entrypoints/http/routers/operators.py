from collections.abc import Sequence
from typing import Annotated, Literal

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status
from pydantic import Field

from ada.core.models.base import Id
from ada.core.models.operators import Operator, OperatorId
from ada.core.models.pipelines import Pipeline
from ada.core.models.schema import Roles, Schema
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["operators"])


class Placement(Request):
    """Where the operator was added from. With a session id, the session records it."""

    session_id: Id | None = None
    note: str = ""


class NewSourceOperator(Placement):
    kind: Literal["source"]
    data_source_id: Id


class NewTransform(Placement):
    kind: Literal["transform"]
    sql: str
    inputs: tuple[OperatorId, ...]
    roles: Roles | None = None
    materialize: bool = False


class NewInput(Placement):
    kind: Literal["input"]
    name: str
    output: Schema
    default: OperatorId


# The kind selects which of the three the body is; any other kind is a 422.
type NewOperator = Annotated[
    NewSourceOperator | NewTransform | NewInput, Field(discriminator="kind")
]


@router.post("/projects/{project_id}/operators", status_code=status.HTTP_201_CREATED)
async def add_operator(
    project_id: Id,
    body: NewOperator,
    projects: FromDishka[ProjectService],
    pipelines: FromDishka[PipelineService],
    sessions: FromDishka[SessionService],
) -> Operator:
    await projects.get(project_id)
    match body:
        case NewSourceOperator():
            operator = await pipelines.add_source(project_id, body.data_source_id, WEB)
        case NewTransform():
            operator = await pipelines.add_transform(
                project_id, body.sql, body.inputs, WEB, body.roles, body.materialize
            )
        case NewInput():
            operator = await pipelines.add_input(
                project_id, body.name, body.output, body.default, WEB
            )
    if body.session_id is not None:
        await sessions.record_operator(body.session_id, operator.id, body.note, WEB)
    return operator


@router.get("/operators/{operator_id}")
async def get_operator(operator_id: OperatorId, service: FromDishka[PipelineService]) -> Operator:
    return await service.get(operator_id)


@router.get("/operators/{operator_id}/lineage")
async def get_lineage(
    operator_id: OperatorId, service: FromDishka[PipelineService]
) -> Sequence[Operator]:
    """The operator and everything upstream of it, inputs first."""
    return await service.lineage(operator_id)


@router.get("/projects/{project_id}/pipelines")
async def list_pipelines(
    project_id: Id, projects: FromDishka[ProjectService], service: FromDishka[PipelineService]
) -> Sequence[Pipeline]:
    """The project's pipelines: operators no other operator uses as an input, newest
    first, with a readable name and the data sources each reads."""
    await projects.get(project_id)
    return await service.pipelines(project_id)
