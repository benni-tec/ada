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
    AnyCompiled,
    AnySpec,
    Evaluation,
    EvaluationInputs,
    ModelSpec,
    ModelVersion,
    PopulationFigure,
    StatisticalModel,
    TrialCompiled,
    TrialMatcherSpec,
)
from ada.core.ports.repositories import (
    CaseRepository,
    ProjectRepository,
    StatisticalModelRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.cases.fields import coverage, describe
from ada.core.services.ports.exploration import MAX_EXPLORATION_ROWS, Clauses, ExplorationService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.statistical_models import pathway, trials_kind
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
        return await self._store(
            project_id, name, description, spec, compile_spec(spec), actor, case_type_id, auto_run
        )

    async def _store(
        self,
        project_id: Id,
        name: str,
        description: str,
        spec: AnySpec,
        compiled: AnyCompiled,
        actor: Actor,
        case_type_id: Id | None,
        auto_run: bool,
    ) -> ModelVersion:
        """Store a new model with its first version, on its case type (the kind's default
        when none is named), which must cover it."""
        await self.projects.get(project_id)
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
        types = await self.cases.list_types(project_id)
        # The kind's own default by name first, then any case type that already covers it.
        for case_type in sorted(types, key=lambda t: t.name != default.name):
            if not coverage(case_type.fields, needs):
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

    async def create_trial_matcher(
        self,
        project_id: Id,
        operator_id: OperatorId,
        actor: Actor,
        case_type_id: Id | None = None,
        auto_run: bool = False,
    ) -> ModelVersion:
        spec = TrialMatcherSpec(operator_id=operator_id)
        compiled = await self._read_trials(spec, actor)
        return await self._store(
            project_id,
            trials_kind.NAME,
            trials_kind.DESCRIPTION,
            spec,
            compiled,
            actor,
            case_type_id,
            auto_run,
        )

    async def refresh_trial_matcher(self, model_id: Id, actor: Actor) -> ModelVersion:
        model = await self.models.get(model_id)
        if model.kind != trials_kind.KIND:
            raise Invalid(f"{model.name} is not a trial matcher")
        latest = await self.models.version(model.id, model.latest_version)
        spec = latest.spec
        assert isinstance(spec, TrialMatcherSpec)
        version = ModelVersion(
            id=uuid7(),
            model_id=model.id,
            version=model.latest_version + 1,
            spec=spec,
            compiled=await self._read_trials(spec, actor),
            created_by=actor,
            created_at=self.clock.now(),
        )
        await self._check_covered(model, version)
        await self.models.add_version(version)
        return version

    async def _read_trials(self, spec: TrialMatcherSpec, actor: Actor) -> TrialCompiled:
        """The trials of the matcher's cancer groups, one row each, with the nearest
        recruiting site from each city, read from the trials data step in a new run."""
        groups = "|".join(sorted(set(spec.groups.values())))
        nearest = ", ".join(
            f"arg_min(facility, km_{c}) AS {c}_facility, arg_min(city, km_{c}) AS {c}_city, "
            f"arg_min(country, km_{c}) AS {c}_country, min(km_{c}) AS {c}_km"
            for c in trials_kind.CITIES
        )
        explored = await self.exploration.query(
            spec.operator_id,
            Clauses(
                select="nct_id, any_value(title) AS title, any_value(phase) AS phase, "
                "any_value(conditions) AS conditions, any_value(cancer_groups) AS cancer_groups, "
                "any_value(sex) AS sex, any_value(min_age_years) AS min_age_years, "
                "any_value(max_age_years) AS max_age_years, "
                "any_value(eligibility) AS eligibility, "
                "any_value(recruiting_countries) AS recruiting_countries, "
                "bool_or(country = 'Finland') AS finnish_site, "
                f"{nearest}, any_value(url) AS url",
                where=f"regexp_matches(cancer_groups, '(^|, )({groups})(,|$)')",
                group_by="nct_id",
                order_by="nct_id",
            ),
            actor,
            limit=MAX_EXPLORATION_ROWS,
        )
        if explored.rows.truncated:
            raise Invalid(
                f"More than {MAX_EXPLORATION_ROWS} recruiting trials match the matcher's cancer "
                "groups: narrow the groups"
            )
        return TrialCompiled(
            trials=tuple(trials_kind.pinned(explored.rows)),
            run_id=None if explored.run_id is None else str(explored.run_id),
            read_at=self.clock.now(),
        )

    async def add_version(self, model_id: Id, spec: ModelSpec, actor: Actor) -> ModelVersion:
        model = await self.models.get(model_id)
        if model.kind != pathway.KIND:
            raise Invalid(f"{model.name} takes no spec of this shape; refresh it instead")
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
