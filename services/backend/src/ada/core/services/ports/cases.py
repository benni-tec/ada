from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.cases import (
    Case,
    CaseResult,
    CaseState,
    CaseType,
    CaseWithResult,
    Field,
    ModelOnCase,
    SavedCase,
)


class CaseService(Protocol):
    """Case types, the cases saved under keys their callers set, and the results of the
    models on a case's type: automatic ones run on every save, the others on request.
    Results are history; a model added later is never backfilled."""

    async def create_type(
        self, project_id: Id, name: str, description: str, fields: tuple[Field, ...], actor: Actor
    ) -> CaseType: ...

    async def update_type(
        self,
        id: Id,
        name: str | None = None,
        description: str | None = None,
        fields: tuple[Field, ...] | None = None,
    ) -> CaseType:
        """Invalid when, while the type has cases, the change does more than add optional
        fields or levels, or when it would leave a model on the type uncovered."""
        ...

    async def get_type(self, id: Id) -> CaseType: ...
    async def list_types(self, project_id: Id) -> Sequence[CaseType]: ...

    async def put_case(
        self, case_type_id: Id, key: str, values: JsonObject, actor: Actor
    ) -> SavedCase:
        """Create or update the case under `key` (never a personal identity code), record
        the steps whose days changed, then run every automatic model on the type and store
        its result."""
        ...

    async def get_case(self, case_type_id: Id, key: str) -> CaseState: ...
    async def list_cases(self, case_type_id: Id) -> Sequence[Case]: ...

    async def models(self, case_type_id: Id, key: str) -> Sequence[ModelOnCase]:
        """Every model on the case's type, with its latest result for the case or none."""
        ...

    async def evaluate(self, case_type_id: Id, key: str, model_id: Id, actor: Actor) -> CaseResult:
        """Run a model on the type on the case now, automatic or not, and store the result."""
        ...

    async def open_cases(self, case_type_id: Id) -> Sequence[CaseWithResult]:
        """Cases whose pathway has not reached treatment start, by their latest pathway
        result: overdue first, then the nearest deadline. Never by survival."""
        ...

    async def model_cases(self, model_id: Id) -> Sequence[CaseWithResult]:
        """Every case of the model's type with the model's latest result for it, or none."""
        ...
