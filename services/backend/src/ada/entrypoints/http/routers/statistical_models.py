"""Statistical models: a project's models, their versions, the population view, and the
evaluation of one profile, which is computed and returned, never stored."""

from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from ada.core.models.base import Id
from ada.core.models.statistical_models import (
    Evaluation,
    EvaluationInputs,
    ModelSpec,
    ModelVersion,
    PopulationFigure,
    StatisticalModel,
)
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["models"])


class NewModel(Request):
    name: str
    description: str = ""
    spec: ModelSpec


class NewVersion(Request):
    spec: ModelSpec


class Evaluate(Request):
    inputs: EvaluationInputs
    # The version to evaluate on; the latest when left out.
    version: int | None = None


@router.get("/projects/{project_id}/models")
async def list_models(
    project_id: Id, service: FromDishka[StatisticalModelService]
) -> Sequence[StatisticalModel]:
    return await service.list(project_id)


@router.post("/projects/{project_id}/models", status_code=201)
async def create_model(
    project_id: Id, body: NewModel, service: FromDishka[StatisticalModelService]
) -> ModelVersion:
    return await service.create(project_id, body.name, body.description, body.spec, WEB)


@router.post("/projects/{project_id}/models/pathway", status_code=201)
async def create_pathway_model(
    project_id: Id, service: FromDishka[StatisticalModelService]
) -> ModelVersion:
    """The patient pathway model (lung cancer, v1), built from the figures and provenance
    shipped with the platform."""
    return await service.create_pathway_model(project_id, WEB)


@router.get("/models/{model_id}")
async def get_model(model_id: Id, service: FromDishka[StatisticalModelService]) -> StatisticalModel:
    return await service.get(model_id)


@router.get("/models/{model_id}/versions/latest")
async def latest_version(
    model_id: Id, service: FromDishka[StatisticalModelService]
) -> ModelVersion:
    return await service.version(model_id)


@router.get("/models/{model_id}/versions/{number}")
async def get_version(
    model_id: Id, number: int, service: FromDishka[StatisticalModelService]
) -> ModelVersion:
    return await service.version(model_id, number)


@router.post("/models/{model_id}/versions", status_code=201)
async def add_version(
    model_id: Id, body: NewVersion, service: FromDishka[StatisticalModelService]
) -> ModelVersion:
    return await service.add_version(model_id, body.spec, WEB)


@router.post("/models/{model_id}/evaluate")
async def evaluate_model(
    model_id: Id, body: Evaluate, service: FromDishka[StatisticalModelService]
) -> Evaluation:
    """Evaluate one synthetic profile. Nothing is stored: no run, no snapshot, no
    operator."""
    return await service.evaluate(model_id, body.inputs, body.version)


@router.get("/models/{model_id}/population")
async def population(
    model_id: Id, service: FromDishka[StatisticalModelService]
) -> Sequence[PopulationFigure]:
    return await service.population(model_id)
