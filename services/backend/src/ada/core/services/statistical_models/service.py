"""Statistical models: create a model with its first version, add versions, evaluate one
profile. Evaluations are computed in this request and returned; nothing is stored."""

from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.cases import CaseType
from ada.core.models.errors import Invalid
from ada.core.models.operators import OperatorId
from ada.core.models.statistical_models import (
    Evaluation,
    EvaluationInputs,
    ModelSpec,
    ModelVersion,
    PopulationFigure,
    StatisticalModel,
)
from ada.core.ports.repositories import (
    CaseRepository,
    ProjectRepository,
    StatisticalModelRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.cases.fields import coverage, describe
from ada.core.services.ports.exploration import Clauses, ExplorationService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.statistical_models import pathway
from ada.core.services.statistical_models.build import (
    PARAMETER_COLUMNS,
    compile_spec,
    read_parameters,
)
from ada.core.services.statistical_models.evaluate import evaluate
from ada.core.services.statistical_models.kinds import kind_of


class StatisticalModels(StatisticalModelService):
    def __init__(
        self,
        models: StatisticalModelRepository,
        projects: ProjectRepository,
        cases: CaseRepository,
        exploration: ExplorationService,
        clock: Clock,
    ) -> None:
        self.models = models
        self.projects = projects
        self.cases = cases
        self.exploration = exploration
        self.clock = clock

    async def create(
        self,
        project_id: Id,
        name: str,
        description: str,
        spec: ModelSpec,
        actor: Actor,
        case_type_id: Id | None = None,
        auto_run: bool = False,
    ) -> ModelVersion:
        await self.projects.get(project_id)
        compiled = compile_spec(spec)
        now = self.clock.now()
        model = StatisticalModel(
            id=uuid7(),
            project_id=project_id,
            name=name,
            description=description,
            kind=spec.kind,
            latest_version=0,
            case_type_id=case_type_id,
            auto_run=auto_run,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        version = ModelVersion(
            id=uuid7(),
            model_id=model.id,
            version=1,
            spec=spec,
            compiled=compiled,
            created_by=actor,
            created_at=now,
        )
        if model.case_type_id is None:
            case_type = await self._default_case_type(project_id, model.kind, version, actor)
            model = model.model_copy(update={"case_type_id": case_type.id})
        await self._check_covered(model, version)
        await self.models.add(model)
        await self.models.add_version(version)
        return version

    async def _default_case_type(
        self, project_id: Id, kind: str, version: ModelVersion, actor: Actor
    ) -> CaseType:
        """The project's case type of the kind's default name when it covers the version,
        else a new one."""
        default = kind_of(kind).default_case_type(version)
        needs = kind_of(kind).requires(version)
        for case_type in await self.cases.list_types(project_id):
            if case_type.name == default.name and not coverage(case_type.fields, needs):
                return case_type
        case_type = CaseType(
            id=uuid7(),
            project_id=project_id,
            name=default.name,
            description=default.description,
            fields=default.fields,
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self.cases.add_type(case_type)
        return case_type

    async def set_case_type(
        self, model_id: Id, case_type_id: Id | None, auto_run: bool
    ) -> StatisticalModel:
        model = await self.models.get(model_id)
        changed = model.model_copy(update={"case_type_id": case_type_id, "auto_run": auto_run})
        await self._check_covered(
            changed, await self.models.version(model.id, model.latest_version)
        )
        await self.models.update(changed)
        return changed

    async def _check_covered(self, model: StatisticalModel, version: ModelVersion) -> None:
        """Invalid unless the model's case type, if it has one, covers what it needs."""
        if model.case_type_id is None:
            return
        case_type = await self.cases.get_type(model.case_type_id)
        if case_type.project_id != model.project_id:
            raise Invalid("A model's case type must be in the model's project")
        gaps = coverage(case_type.fields, kind_of(model.kind).requires(version))
        if gaps:
            raise Invalid(f"{case_type.name} does not cover {model.name}: {describe(gaps)}")

    async def create_pathway_model(
        self, project_id: Id, actor: Actor, parameters: OperatorId | None = None
    ) -> ModelVersion:
        spec = pathway.pathway_spec()
        if parameters is not None:
            explored = await self.exploration.query(
                parameters, Clauses(select=", ".join(PARAMETER_COLUMNS)), actor, limit=500
            )
            if explored.rows.truncated:
                raise Invalid(f"operator {parameters} has more rows than one model reads")
            spec = read_parameters(spec, explored.rows, parameters, str(explored.run_id))
        return await self.create(
            project_id, pathway.NAME, pathway.DESCRIPTION, spec, actor, auto_run=True
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
        await self._check_covered(model, version)
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
        await self._survival(model_id)
        return evaluate(await self.version(model_id, number), inputs)

    async def population(
        self, model_id: Id, number: int | None = None
    ) -> Sequence[PopulationFigure]:
        await self._survival(model_id)
        return (await self.version(model_id, number)).compiled.population

    async def _survival(self, model_id: Id) -> None:
        """Invalid unless the model is of the survival kind: a profile's evaluation and the
        population view are that kind's."""
        model = await self.models.get(model_id)
        if model.kind != pathway.KIND:
            raise Invalid(f"{model.name} is a {model.kind} model: it has no profile evaluation")
