from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id
from ada.core.models.operators import OperatorId
from ada.core.models.statistical_models import (
    Evaluation,
    EvaluationInputs,
    ModelSpec,
    ModelVersion,
    PopulationFigure,
    StatisticalModel,
)


class StatisticalModelService(Protocol):
    """Versioned models built from published figures, evaluated on one profile at a time.
    An evaluation is computed and returned; it creates no run, snapshot or operator."""

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
        """Create a model with its first version. Invalid when the spec does not hold
        together (a site without a baseline, a criterion or target for an unknown site,
        an unknown toggle, an empty intended use), or when `case_type_id` names a case type
        that does not cover what the model needs."""
        ...

    async def set_case_type(
        self, model_id: Id, case_type_id: Id | None, auto_run: bool
    ) -> StatisticalModel:
        """Put a model on a case type (or none) and say whether it runs on every save.
        Invalid when the case type does not cover what the latest version needs."""
        ...

    async def create_pathway_model(
        self, project_id: Id, actor: Actor, parameters: OperatorId | None = None
    ) -> ModelVersion:
        """Create the patient pathway model from the figures and provenance in
        `ada.core.services.statistical_models.pathway`, on the project's "Suspected cancer
        pathway" case type (created when there is none that covers it), running
        automatically. With `parameters`, the effect sizes
        are read from that operator instead (columns name, estimate, ci_low, ci_high,
        source_id, passage, found), each cited by the operator and the run it was read in.
        Invalid when a row names an unknown parameter, a passage was not found in its
        source, or a parameter cited to a registered source has no row."""
        ...

    async def add_version(self, model_id: Id, spec: ModelSpec, actor: Actor) -> ModelVersion:
        """Build a new version; the old ones stay as they are. Invalid when the model's
        case type does not cover the new version."""
        ...

    async def list(self, project_id: Id) -> Sequence[StatisticalModel]: ...
    async def get(self, id: Id) -> StatisticalModel: ...

    async def version(self, model_id: Id, number: int | None = None) -> ModelVersion:
        """A version, the latest when `number` is None."""
        ...

    async def evaluate(
        self, model_id: Id, inputs: EvaluationInputs, number: int | None = None
    ) -> Evaluation:
        """Evaluate one profile on a version. Invalid when an input is not among the
        terms' levels, or names a site the version has no baseline for."""
        ...

    async def population(
        self, model_id: Id, number: int | None = None
    ) -> Sequence[PopulationFigure]:
        """The population view stored at build: per site and sex, the baseline, the
        baseline with the comparison country's days, and that country's observed
        survival."""
        ...
