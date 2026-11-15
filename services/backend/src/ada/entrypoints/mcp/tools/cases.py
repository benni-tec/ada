from collections.abc import Sequence

from dishka import FromDishka
from fastmcp import FastMCP

from ada.core.models.base import Id, JsonObject
from ada.core.models.cases import (
    CaseResult,
    CaseState,
    CaseType,
    CaseWithResult,
    Field,
    SavedCase,
)
from ada.core.services.ports.cases import CaseService
from ada.entrypoints.mcp.actor import calling_agent
from ada.entrypoints.mcp.injection import Inject
from ada.entrypoints.mcp.sessions import SessionId


def register(mcp: FastMCP, inject: Inject) -> None:
    @mcp.tool
    @inject
    async def list_case_types(
        project_id: Id, session_id: SessionId, service: FromDishka[CaseService]
    ) -> Sequence[CaseType]:
        """List a project's case types, each with its fields (name, type, levels, required).
        A case is saved under a case type; the models on the type run on its cases."""
        return await service.list_types(project_id)

    @mcp.tool
    @inject
    async def create_case_type(
        project_id: Id,
        session_id: SessionId,
        name: str,
        fields: list[Field],
        service: FromDishka[CaseService],
        description: str = "",
    ) -> CaseType:
        """Create a case type: the fields its cases hold. Types: text, number, integer,
        date, boolean, enum (one of `levels`), enum_list (several of `levels`), day_map
        (`levels` -> whole days). A model on the type needs every field it reads; extra
        fields are saved with the case and appear in its data, but no model sees them."""
        return await service.create_type(
            project_id, name, description, tuple(fields), calling_agent()
        )

    @mcp.tool
    @inject
    async def set_case(
        case_type_id: Id,
        key: str,
        values: JsonObject,
        session_id: SessionId,
        service: FromDishka[CaseService],
    ) -> SavedCase:
        """Create or update the case under `key`, a reference into another system (never a
        personal identity code). Values are checked against the case type's fields. The
        models on the type set to run automatically run now; their results are stored on
        the case, as history. Synthetic data only: the platform is not for patient data."""
        return await service.put_case(case_type_id, key, values, calling_agent())

    @mcp.tool
    @inject
    async def get_case(
        case_type_id: Id, key: str, session_id: SessionId, service: FromDishka[CaseService]
    ) -> CaseState:
        """A case's values, its step events and every result the models produced for it,
        newest first."""
        return await service.get_case(case_type_id, key)

    @mcp.tool
    @inject
    async def evaluate_case(
        case_type_id: Id,
        key: str,
        model_id: Id,
        session_id: SessionId,
        service: FromDishka[CaseService],
    ) -> CaseResult:
        """Run a model on a case now and store the result on the case, whether or not the
        model runs automatically. Models added after a case was saved have no result for it
        until this is called."""
        return await service.evaluate(case_type_id, key, model_id, calling_agent())

    @mcp.tool
    @inject
    async def list_open_cases(
        case_type_id: Id, session_id: SessionId, service: FromDishka[CaseService]
    ) -> Sequence[CaseWithResult]:
        """The cases needing attention: those a model's latest result says are still open,
        each with its most urgent open result, ordered by status, then the most overdue,
        then the soonest due. Never ordered by survival."""
        return await service.open_cases(case_type_id)
