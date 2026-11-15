from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import DomainModel, Id
from ada.core.models.operators import OperatorId
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
        project_id: Id,
        session_id: SessionId,
        service: FromDishka[StatisticalModelService],
        parameters: OperatorId | None = None,
    ) -> ModelVersion:
        """Create the patient pathway model in a project: lung, colorectal and pancreatic
        cancer, built from the Danish, Norwegian and Swedish fast-track pathway standards
        (the trigger criteria and the standard times), the Nordic survival level, Finnish
        education effects (Zai 2025) and published delay effects (Hanna 2020, Heiden 2021,
        Sud 2020), each with its provenance. Educational use with synthetic profiles only;
        never patient data.

        `parameters`: an operator to read the effect sizes from, with the columns name,
        estimate, ci_low, ci_high, source_id, passage and found (whether the passage is in
        its source as fetched); each figure is then cited by that operator and run.
        Returns the version with its spec and what the build derived (targets,
        population view)."""
        return await service.create_pathway_model(project_id, calling_agent(), parameters)

    @mcp.tool
    @inject
    async def create_trial_matcher(
        project_id: Id,
        session_id: SessionId,
        operator_id: OperatorId,
        service: FromDishka[StatisticalModelService],
        case_type_id: Id | None = None,
        auto_run: bool = False,
    ) -> ModelVersion:
        """Create a trial matcher: recruiting Nordic cancer trials a case could be discussed
        for, matched on cancer group, sex and age group; trials with a Finnish site first,
        then the nearest site from the case's county. Eligibility text is shown, never
        judged. `operator_id` is a `case_trials` data step (docs/trials.md; in the "Nordic
        cancer trials" project its note starts `case_trials:`). The first version pins the
        trials as read now; `refresh_trial_matcher` reads them again. It runs on
        `case_type_id`, else on a case type that covers it (the cancer pathway one when the
        project has it); `auto_run` runs it on every save of a case."""
        return await service.create_trial_matcher(
            project_id, operator_id, calling_agent(), case_type_id, auto_run
        )

    @mcp.tool
    @inject
    async def refresh_trial_matcher(
        model_id: Id, session_id: SessionId, service: FromDishka[StatisticalModelService]
    ) -> ModelVersion:
        """Make a new version of a trial matcher with the trials read again from its data
        step. Earlier versions, and the results made with them, stay as they were."""
        return await service.refresh_trial_matcher(model_id, calling_agent())

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
