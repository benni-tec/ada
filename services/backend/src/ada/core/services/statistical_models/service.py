"""Statistical models: create a model with its first version, add versions, evaluate one
profile. Evaluations are computed in this request and returned; nothing is stored."""

from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.statistical_models import (
    Evaluation,
    EvaluationInputs,
    ModelSpec,
    ModelVersion,
    PopulationFigure,
    StatisticalModel,
)
from ada.core.ports.repositories import ProjectRepository, StatisticalModelRepository
from ada.core.ports.system import Clock
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.statistical_models import pathway
from ada.core.services.statistical_models.build import compile_spec
from ada.core.services.statistical_models.evaluate import evaluate


class StatisticalModels(StatisticalModelService):
    def __init__(
        self, models: StatisticalModelRepository, projects: ProjectRepository, clock: Clock
    ) -> None:
        self.models = models
        self.projects = projects
        self.clock = clock

    async def create(
        self, project_id: Id, name: str, description: str, spec: ModelSpec, actor: Actor
    ) -> ModelVersion:
        await self.projects.get(project_id)
        compiled = compile_spec(spec)
        now = self.clock.now()
        model = StatisticalModel(
            id=uuid7(),
            project_id=project_id,
            name=name,
            description=description,
            kind=pathway.KIND,
            latest_version=0,
            created_by=actor,
            created_at=now,
        )
        await self.models.add(model)
        version = ModelVersion(
            id=uuid7(),
            model_id=model.id,
            version=1,
            spec=spec,
            compiled=compiled,
            created_by=actor,
            created_at=now,
        )
        await self.models.add_version(version)
        return version

    async def create_pathway_model(self, project_id: Id, actor: Actor) -> ModelVersion:
        return await self.create(
            project_id, pathway.NAME, pathway.DESCRIPTION, pathway.pathway_spec(), actor
        )

    async def add_version(self, model_id: Id, spec: ModelSpec, actor: Actor) -> ModelVersion:
        model = await self.models.get(model_id)
        compiled = compile_spec(spec)
        version = ModelVersion(
            id=uuid7(),
            model_id=model.id,
            version=model.latest_version + 1,
            spec=spec,
            compiled=compiled,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.models.add_version(version)
        return version

    async def list(self, project_id: Id) -> Sequence[StatisticalModel]:
        return await self.models.list(project_id)

    async def get(self, id: Id) -> StatisticalModel:
        return await self.models.get(id)

    async def version(self, model_id: Id, number: int | None = None) -> ModelVersion:
        if number is None:
            number = (await self.models.get(model_id)).latest_version
        return await self.models.version(model_id, number)

    async def evaluate(
        self, model_id: Id, inputs: EvaluationInputs, number: int | None = None
    ) -> Evaluation:
        return evaluate(await self.version(model_id, number), inputs)

    async def population(
        self, model_id: Id, number: int | None = None
    ) -> Sequence[PopulationFigure]:
        return (await self.version(model_id, number)).compiled.population
