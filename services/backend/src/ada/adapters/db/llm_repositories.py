"""The in-platform agent's configuration: model providers, their models, the settings row
that names the session agent, and the judges' settings, which name models too. Shared by
all projects, but for the projects' judge overrides."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.adapters.db.support import add_row, fetch, oldest_first, require, rows, update_row
from ada.adapters.db.tables import (
    AgentSettingsRow,
    JudgeDefaultsRow,
    LlmModelRow,
    LlmProviderRow,
    ProjectJudgeRow,
    ProjectRow,
)
from ada.core.models.agents import AgentSettings, LlmModel, LlmProvider, ProviderKind
from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.judges import JudgeDefaults, JudgeKind, JudgeOverride, Strictness
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    JudgeSettingsRepository,
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
        model_ids: dict[str, UUID | None] = {}
        for column, model in (
            ("session_agent_model_id", settings.session_agent),
            ("research_agent_model_id", settings.research_agent),
        ):
            model_ids[column] = (
                (await _model_row(self.session, model))[0].id if model is not None else None
            )
        row = await update_row(
            self.session,
            AgentSettingsRow,
            "agent settings",
            SETTINGS_ID,
            expected_revision,
            {**model_ids, "instructions": settings.instructions},
        )
        return await self._settings(row)

    async def _settings(self, row: AgentSettingsRow) -> AgentSettings:
        return AgentSettings(
            session_agent=await self._model_id(row.session_agent_model_id),
            research_agent=await self._model_id(row.research_agent_model_id),
            instructions=row.instructions,
            revision=row.revision,
        )

    async def _model_id(self, id: UUID | None) -> str | None:
        if id is None:
            return None
        found = (await self.session.execute(_models().where(LlmModelRow.id == id))).first()
        return _model(found[0], found[1]).id if found is not None else None


async def _model_uuid(session: AsyncSession, id: str | None) -> UUID | None:
    return (await _model_row(session, id))[0].id if id is not None else None


async def _model_name(session: AsyncSession, id: UUID | None) -> str | None:
    if id is None:
        return None
    found = (await session.execute(_models().where(LlmModelRow.id == id))).first()
    return _model(found[0], found[1]).id if found is not None else None


class SqlJudgeSettingsRepository(JudgeSettingsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def defaults(self) -> Sequence[JudgeDefaults]:
        statement = select(JudgeDefaultsRow).order_by(JudgeDefaultsRow.kind)
        return [await self._defaults(row) for row in await rows(self.session, statement)]

    async def update_defaults(
        self, defaults: JudgeDefaults, expected_revision: int
    ) -> JudgeDefaults:
        row = await update_row(
            self.session,
            JudgeDefaultsRow,
            "judge defaults",
            defaults.kind.value,
            expected_revision,
            {
                "strictness": defaults.strictness.value,
                "model_id": await _model_uuid(self.session, defaults.model_id),
                "instructions": defaults.instructions,
            },
        )
        return await self._defaults(row)

    async def overrides(self, project_id: Id) -> Sequence[JudgeOverride]:
        statement = (
            select(ProjectJudgeRow)
            .where(ProjectJudgeRow.project_id == project_id)
            .order_by(ProjectJudgeRow.kind)
        )
        return [await self._override(row) for row in await rows(self.session, statement)]

    async def save_override(self, override: JudgeOverride, expected_revision: int) -> JudgeOverride:
        values = {
            "strictness": override.strictness.value if override.strictness else None,
            "model_id": await _model_uuid(self.session, override.model_id),
            "instructions": override.instructions,
        }
        key = (override.project_id, override.kind.value)
        if expected_revision == 0:
            await require(self.session, ProjectRow, override.project_id, "project")
            existing = await self.session.get(ProjectJudgeRow, key, populate_existing=True)
            if existing is not None:
                raise Conflict("judge override", override.kind, 0, existing.revision)
            row = ProjectJudgeRow(
                project_id=override.project_id, kind=override.kind.value, **values
            )
            await add_row(self.session, row)
            return await self._override(row)
        row = await update_row(
            self.session, ProjectJudgeRow, "judge override", key, expected_revision, values
        )
        return await self._override(row)

    async def _defaults(self, row: JudgeDefaultsRow) -> JudgeDefaults:
        return JudgeDefaults(
            kind=JudgeKind(row.kind),
            strictness=Strictness(row.strictness),
            model_id=await _model_name(self.session, row.model_id),
            instructions=row.instructions,
            revision=row.revision,
        )

    async def _override(self, row: ProjectJudgeRow) -> JudgeOverride:
        return JudgeOverride(
            project_id=row.project_id,
            kind=JudgeKind(row.kind),
            strictness=Strictness(row.strictness) if row.strictness is not None else None,
            model_id=await _model_name(self.session, row.model_id),
            instructions=row.instructions,
            revision=row.revision,
        )
