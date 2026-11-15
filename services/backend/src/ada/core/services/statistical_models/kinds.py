"""The kinds of statistical model, and what each needs to run on cases. A kind says which
fields of a case it reads, names the data steps it reads when it runs, runs on a case's
values and those rows, declares the columns its results can have, and brings a default case
type. The patient pathway model and the trial matcher are the kinds; a new kind is one more
entry in KINDS."""

from typing import Protocol

from ada.core.models.analysis import Rows
from ada.core.models.base import JsonObject
from ada.core.models.cases import DefaultCaseType, Field, Section
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column
from ada.core.models.statistical_models import ModelVersion
from ada.core.services.ports.exploration import Clauses
from ada.core.services.statistical_models import pathway, trials_kind
from ada.core.services.statistical_models.pathway_kind import PathwayKind


class ModelKind(Protocol):
    def requires(self, version: ModelVersion) -> tuple[Field, ...]:
        """The fields this version reads, with the levels it accepts."""
        ...

    def queries(self, version: ModelVersion, values: JsonObject) -> dict[str, tuple[str, Clauses]]:
        """The data steps this version reads for a case, by a name of its own: each an
        operator and one query over its output. Run in a new run each time the model runs,
        so the result is as current as the data; the run is recorded on the result."""
        ...

    def run(self, version: ModelVersion, values: JsonObject, data: dict[str, Rows]) -> Section:
        """The version's result for a case's values (only the fields it requires) and the
        rows of its queries, with its attention filled in."""
        ...

    def columns(self, version: ModelVersion) -> tuple[Column, ...]:
        """Every column a section of this version can have (`Section.columns`), with its
        type, unprefixed: the cases source declares them for its results table."""
        ...

    def default_case_type(self, version: ModelVersion) -> DefaultCaseType:
        """The case type a model of this kind gets when it is created without one: at
        least the fields it requires."""
        ...


KINDS: dict[str, ModelKind] = {
    pathway.KIND: PathwayKind(),
    trials_kind.KIND: trials_kind.TrialKind(),
}


def kind_of(name: str) -> ModelKind:
    try:
        return KINDS[name]
    except KeyError:
        raise Invalid(f"No model kind {name} is known") from None
