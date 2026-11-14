from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import DomainModel, Id
from ada.core.models.statistical_models import (
    Evaluation,
    EvaluationInputs,
    ModelVersion,
    StatisticalModel,
)
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId


class ModelState(DomainModel):
    model: StatisticalModel
    version: ModelVersion
    # Where a person sees it in the frontend, relative to the host serving ADA.
    url: str


def model_url(model: StatisticalModel) -> str:
    return f"/projects/{model.project_id}/models/{model.id}"


async def _state(service: StatisticalModelService, id: Id) -> ModelState:
    model = await service.get(id)
    return ModelState(model=model, version=await service.version(id), url=model_url(model))


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def create_pathway_model(
        project_id: Id, session_id: SessionId, service: FromDishka[StatisticalModelService]
    ) -> ModelVersion:
        """Create the patient pathway model in a project: lung cancer, v1, built from the
        Norwegian and Swedish fast-track pathway standards (the trigger criteria and the
        standard times), the Nordic survival level, Finnish education effects (Zai 2025)
        and published delay effects (Hanna 2020, Heiden 2021, Sud 2020), each with its
        provenance. Educational use with synthetic profiles only; never patient data.
        Returns the version with its spec and what the build derived (targets,
        population view)."""
        return await service.create_pathway_model(project_id, calling_agent())

    @mcp.tool
    @inject
    async def list_models(
        project_id: Id, session_id: SessionId, service: FromDishka[StatisticalModelService]
    ) -> Sequence[StatisticalModel]:
        """List a project's statistical models, each with its latest version number."""
        return await service.list(project_id)

    @mcp.tool
    @inject
    async def get_model(
        model_id: Id, session_id: SessionId, service: FromDishka[StatisticalModelService]
    ) -> ModelState:
        """A model with its latest version: the sites, the terms and their levels, the
        trigger criteria (with ids to pass as `presentation`), the targets, the
        parameters with their provenance and evidence grade, the toggles, and the
        population view. Read it before `evaluate_model`."""
        return await _state(service, model_id)

    @mcp.tool
    @inject
    async def evaluate_model(
        model_id: Id,
        session_id: SessionId,
        inputs: EvaluationInputs,
        service: FromDishka[StatisticalModelService],
        version: int | None = None,
    ) -> Evaluation:
        """Evaluate one synthetic example profile on the model (educational use; never
        patient data). `inputs`: the site, sex, age band, education, route of first
        contact, stage and treatment intent if known, `presentation` (ids of the criteria
        the presentation meets, from `get_model`), and `days` spent in each pathway step
        so far (a step left out has not started). Lead with the result's `trigger` and
        `deadlines`, which are exact (the national standards), then `days_behind`; the
        `survival` figures come second, per setting of the toggles, and each lever names
        its evidence grade. Nothing is stored."""
        return await service.evaluate(model_id, inputs, version)
