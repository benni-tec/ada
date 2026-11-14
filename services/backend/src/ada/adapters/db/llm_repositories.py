"""The in-platform agent's configuration: model providers, their models, and the settings
row that names the session agent. Shared by all projects."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import add_row, fetch, oldest_first, require, rows, update_row
from ada.adapters.db.tables import AgentSettingsRow, LlmModelRow, LlmProviderRow
from ada.core.models.agents import AgentSettings, LlmModel, LlmProvider, ProviderKind
from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.errors import NotFound
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    LlmModelRepository,
    LlmProviderRepository,
)

PROVIDER = "llm provider"
MODEL = "model"
# The one row of agent_settings, inserted by migration 0005.
SETTINGS_ID = 1


def _provider(row: LlmProviderRow) -> LlmProvider:
    return LlmProvider(
        id=row.id,
        name=row.name,
        kind=ProviderKind(row.kind),
        base_url=row.base_url,
        has_api_key=row.api_key_encrypted is not None,
        created_at=row.created_at,
        revision=row.revision,
    )


class SqlLlmProviderRepository(LlmProviderRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Id) -> LlmProvider:
        return _provider(await fetch(self.session, LlmProviderRow, id, PROVIDER))

    async def list(self) -> Sequence[LlmProvider]:
        return [_provider(row) for row in await rows(self.session, oldest_first(LlmProviderRow))]

    async def add(self, provider: LlmProvider, api_key: str | None) -> LlmProvider:
        row = LlmProviderRow(
            id=provider.id,
            name=provider.name,
            kind=provider.kind.value,
            base_url=provider.base_url,
            api_key_encrypted=api_key,
            created_at=provider.created_at,
        )
        await add_row(self.session, row)
        return _provider(row)

    async def update(
        self,
        provider: LlmProvider,
        expected_revision: int,
        api_key: Change[str | None] = UNCHANGED,
    ) -> LlmProvider:
        changes: dict[str, Any] = {
            "name": provider.name,
            "kind": provider.kind.value,
            "base_url": provider.base_url,
        }
        if api_key is not UNCHANGED:
            changes["api_key_encrypted"] = api_key
        row = await update_row(
            self.session, LlmProviderRow, PROVIDER, provider.id, expected_revision, changes
        )
        return _provider(row)

    async def delete(self, id: Id) -> None:
        # The database removes its models (CASCADE) and clears a session agent among them
        # (SET NULL).
        result = await self.session.execute(delete(LlmProviderRow).where(LlmProviderRow.id == id))
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NotFound(PROVIDER, id)

    async def api_key(self, id: Id) -> str | None:
        return (await fetch(self.session, LlmProviderRow, id, PROVIDER)).api_key_encrypted


def _models() -> Select[Any]:
    return select(LlmModelRow, LlmProviderRow.name).join(
        LlmProviderRow, LlmProviderRow.id == LlmModelRow.provider_id
    )


def _model(row: LlmModelRow, provider_name: str) -> LlmModel:
    return LlmModel(
        id=f"{provider_name}/{row.model}",
        provider_id=row.provider_id,
        model=row.model,
        created_at=row.created_at,
    )


async def _model_row(session: AsyncSession, id: str) -> tuple[LlmModelRow, str]:
    provider_name, _, model = id.partition("/")
    statement = _models().where(LlmProviderRow.name == provider_name, LlmModelRow.model == model)
    found = (await session.execute(statement.execution_options(populate_existing=True))).first()
    if found is None or not model:
        raise NotFound(MODEL, id)
    return found[0], found[1]


class SqlLlmModelRepository(LlmModelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: str) -> LlmModel:
        return _model(*await _model_row(self.session, id))

    async def list(self) -> Sequence[LlmModel]:
        statement = _models().order_by(LlmModelRow.created_at, LlmModelRow.id)
        result = await self.session.execute(statement.execution_options(populate_existing=True))
        return [_model(row, name) for row, name in result.all()]

    async def add(self, model: LlmModel) -> LlmModel:
        await require(self.session, LlmProviderRow, model.provider_id, PROVIDER)
        row = LlmModelRow(
            id=uuid7(),
            provider_id=model.provider_id,
            model=model.model,
            created_at=model.created_at,
        )
        await add_row(self.session, row)
        provider = await fetch(self.session, LlmProviderRow, model.provider_id, PROVIDER)
        return _model(row, provider.name)

    async def delete(self, id: str) -> None:
        row, _ = await _model_row(self.session, id)
        # A session agent naming it is cleared by the database (SET NULL).
        await self.session.execute(delete(LlmModelRow).where(LlmModelRow.id == row.id))


class SqlAgentSettingsRepository(AgentSettingsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> AgentSettings:
        row = await fetch(self.session, AgentSettingsRow, SETTINGS_ID, "agent settings")
        return await self._settings(row)

    async def update(self, settings: AgentSettings, expected_revision: int) -> AgentSettings:
        model_id: UUID | None = None
        if settings.session_agent is not None:
            model_id = (await _model_row(self.session, settings.session_agent))[0].id
        row = await update_row(
            self.session,
            AgentSettingsRow,
            "agent settings",
            SETTINGS_ID,
            expected_revision,
            {"session_agent_model_id": model_id, "instructions": settings.instructions},
        )
        return await self._settings(row)

    async def _settings(self, row: AgentSettingsRow) -> AgentSettings:
        session_agent = None
        if row.session_agent_model_id is not None:
            statement = _models().where(LlmModelRow.id == row.session_agent_model_id)
            found = (await self.session.execute(statement)).first()
            if found is not None:
                session_agent = _model(found[0], found[1]).id
        return AgentSettings(
            session_agent=session_agent, instructions=row.instructions, revision=row.revision
        )
