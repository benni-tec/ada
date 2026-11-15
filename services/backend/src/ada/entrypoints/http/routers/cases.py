"""Case types and cases: saving a case under a key we set runs the automatic models on its
type; any model on the type can be evaluated on a case on request. Results are history."""

from collections.abc import Sequence

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from ada.core.models.base import Id, JsonObject
from ada.core.models.cases import (
    CaseResult,
    CaseState,
    CaseType,
    CaseWithResult,
    CaseWithResults,
    Field,
    ModelOnCase,
    SavedCase,
)
from ada.core.models.statistical_models import StatisticalModel
from ada.core.services.ports.cases import CaseService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.entrypoints.http.actor import WEB
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["cases"])


class NewCaseType(Request):
    name: str
    description: str = ""
    fields: tuple[Field, ...]


class CaseTypeChange(Request):
    name: str | None = None
    description: str | None = None
    fields: tuple[Field, ...] | None = None


class CaseValues(Request):
    values: JsonObject


class EvaluateCase(Request):
    model_id: Id


class ModelCaseType(Request):
    case_type_id: Id | None
    auto_run: bool = False


@router.get("/projects/{project_id}/case-types")
async def list_case_types(project_id: Id, service: FromDishka[CaseService]) -> Sequence[CaseType]:
    return await service.list_types(project_id)


@router.post("/projects/{project_id}/case-types", status_code=201)
async def create_case_type(
    project_id: Id, body: NewCaseType, service: FromDishka[CaseService]
) -> CaseType:
    return await service.create_type(project_id, body.name, body.description, body.fields, WEB)


@router.get("/case-types/{case_type_id}")
async def get_case_type(case_type_id: Id, service: FromDishka[CaseService]) -> CaseType:
    return await service.get_type(case_type_id)


@router.patch("/case-types/{case_type_id}")
async def update_case_type(
    case_type_id: Id, body: CaseTypeChange, service: FromDishka[CaseService]
) -> CaseType:
    return await service.update_type(case_type_id, body.name, body.description, body.fields)


@router.get("/case-types/{case_type_id}/cases")
async def list_cases(
    case_type_id: Id, service: FromDishka[CaseService]
) -> Sequence[CaseWithResults]:
    """Every case of the type, oldest first, with each model's latest result for it."""
    return await service.list_cases(case_type_id)


@router.get("/case-types/{case_type_id}/open-cases")
async def open_cases(
    case_type_id: Id, service: FromDishka[CaseService]
) -> Sequence[CaseWithResult]:
    """The cases needing attention, each with its most urgent open result: by status, the
    most overdue, the soonest due. Never by survival."""
    return await service.open_cases(case_type_id)


@router.get("/case-types/{case_type_id}/cases/{key}")
async def get_case(case_type_id: Id, key: str, service: FromDishka[CaseService]) -> CaseState:
    return await service.get_case(case_type_id, key)


@router.put("/case-types/{case_type_id}/cases/{key}")
async def put_case(
    case_type_id: Id, key: str, body: CaseValues, service: FromDishka[CaseService]
) -> SavedCase:
    """Create or update the case under `key`; the automatic models run and their results
    are stored on it."""
    return await service.put_case(case_type_id, key, body.values, WEB)


@router.get("/case-types/{case_type_id}/cases/{key}/models")
async def case_models(
    case_type_id: Id, key: str, service: FromDishka[CaseService]
) -> Sequence[ModelOnCase]:
    return await service.models(case_type_id, key)


@router.post("/case-types/{case_type_id}/cases/{key}/evaluate", status_code=201)
async def evaluate_case(
    case_type_id: Id, key: str, body: EvaluateCase, service: FromDishka[CaseService]
) -> CaseResult:
    return await service.evaluate(case_type_id, key, body.model_id, WEB)


@router.get("/models/{model_id}/cases")
async def model_cases(model_id: Id, service: FromDishka[CaseService]) -> Sequence[CaseWithResult]:
    """Every case of the model's case type, with the model's latest result or none."""
    return await service.model_cases(model_id)


@router.put("/models/{model_id}/case-type")
async def set_model_case_type(
    model_id: Id, body: ModelCaseType, service: FromDishka[StatisticalModelService]
) -> StatisticalModel:
    return await service.set_case_type(model_id, body.case_type_id, body.auto_run)
