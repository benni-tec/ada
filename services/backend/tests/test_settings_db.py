"""The agent's configuration repositories: the same expectations against the memory
repositories (the reference) and the database ones."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import db_helpers
from ada.adapters.db.llm_repositories import (
    SqlAgentSettingsRepository,
    SqlJudgeSettingsRepository,
    SqlLlmModelRepository,
    SqlLlmProviderRepository,
)
from ada.adapters.db.workspace_repositories import SqlProjectRepository
from ada.adapters.memory.repositories import (
    MemoryAgentSettingsRepository,
    MemoryJudgeSettingsRepository,
    MemoryLlmModelRepository,
    MemoryLlmProviderRepository,
    MemoryProjectRepository,
    MemoryStore,
)
from ada.core.models.agents import LlmModel, LlmProvider, ProviderKind
from ada.core.models.errors import Conflict, NotFound
from ada.core.models.judges import JudgeKind, JudgeOverride, Strictness
from ada.core.models.projects import Project
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    JudgeSettingsRepository,
    LlmModelRepository,
    LlmProviderRepository,
    ProjectRepository,
)

pytestmark = pytest.mark.anyio

AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@dataclass
class Repos:
    providers: LlmProviderRepository
    models: LlmModelRepository
    settings: AgentSettingsRepository
    judges: JudgeSettingsRepository
    projects: ProjectRepository


@pytest.fixture(params=["memory", "database"])
async def repos(request: pytest.FixtureRequest) -> AsyncIterator[Repos]:
    if request.param == "memory":
        store = MemoryStore()
        yield Repos(
            MemoryLlmProviderRepository(store),
            MemoryLlmModelRepository(store),
            MemoryAgentSettingsRepository(store),
            MemoryJudgeSettingsRepository(store),
            MemoryProjectRepository(store),
        )
        return
    url: str = request.getfixturevalue("migrated_database_url")
    async with db_helpers.engine_for(url) as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            yield Repos(
                SqlLlmProviderRepository(session),
                SqlLlmModelRepository(session),
                SqlAgentSettingsRepository(session),
                SqlJudgeSettingsRepository(session),
                SqlProjectRepository(session),
            )


def provider(name: str = "gemini") -> LlmProvider:
    return LlmProvider(id=uuid7(), name=name, kind=ProviderKind.GEMINI, created_at=AT)


async def with_model(repos: Repos, name: str = "gemini") -> tuple[LlmProvider, LlmModel]:
    stored = await repos.providers.add(provider(name), "token")
    model = await repos.models.add(
        LlmModel(id="", provider_id=stored.id, model="flash/2", created_at=AT)
    )
    return stored, model


async def test_a_provider_keeps_its_key_apart_and_counts_its_revision(repos: Repos) -> None:
    stored = await repos.providers.add(provider(), "token-1")

    assert (stored.has_api_key, stored.revision) == (True, 1)
    assert await repos.providers.api_key(stored.id) == "token-1"

    renamed = await repos.providers.update(stored.model_copy(update={"name": "google"}), 1)
    assert (renamed.name, renamed.revision, renamed.has_api_key) == ("google", 2, True)
    cleared = await repos.providers.update(renamed, 2, api_key=None)
    assert not cleared.has_api_key and await repos.providers.api_key(stored.id) is None
    with pytest.raises(Conflict):
        await repos.providers.update(cleared, 1, api_key="token-2")
    assert [p.name for p in await repos.providers.list()] == ["google"]


async def test_a_model_is_addressed_by_its_provider_s_current_name(repos: Repos) -> None:
    stored, model = await with_model(repos)

    assert model.id == "gemini/flash/2"
    await repos.providers.update(stored.model_copy(update={"name": "google"}), 1)

    assert [m.id for m in await repos.models.list()] == ["google/flash/2"]
    assert (await repos.models.get("google/flash/2")).model == "flash/2"
    with pytest.raises(NotFound):
        await repos.models.get("gemini/flash/2")


async def test_the_instructions_are_stored_beside_the_session_agent(repos: Repos) -> None:
    _, model = await with_model(repos)
    settings = await repos.settings.get()
    assert settings.instructions == ""

    told = await repos.settings.update(settings.model_copy(update={"instructions": "Be brief"}), 1)
    chosen = await repos.settings.update(told.model_copy(update={"session_agent": model.id}), 2)

    assert (chosen.instructions, chosen.session_agent, chosen.revision) == ("Be brief", model.id, 3)
    assert (await repos.settings.get()).instructions == "Be brief"


async def test_the_session_agent_is_cleared_with_its_model_or_provider(repos: Repos) -> None:
    stored, model = await with_model(repos)
    _, other = await with_model(repos, "other")

    settings = await repos.settings.get()
    assert (settings.session_agent, settings.revision) == (None, 1)
    chosen = await repos.settings.update(settings.model_copy(update={"session_agent": model.id}), 1)
    assert (chosen.session_agent, chosen.revision) == (model.id, 2)
    with pytest.raises(Conflict):
        await repos.settings.update(chosen, 1)
    with pytest.raises(NotFound):
        await repos.settings.update(chosen.model_copy(update={"session_agent": "x/y"}), 2)

    await repos.providers.delete(stored.id)

    assert (await repos.settings.get()).session_agent is None
    assert [m.id for m in await repos.models.list()] == [other.id]

    await repos.settings.update(chosen.model_copy(update={"session_agent": other.id}), 2)
    await repos.models.delete(other.id)
    assert (await repos.settings.get()).session_agent is None
    with pytest.raises(NotFound):
        await repos.providers.delete(stored.id)


async def test_judge_settings_name_models_and_lose_them_with_the_model(repos: Repos) -> None:
    _, model = await with_model(repos)
    project = Project(id=uuid7(), name="P", created_at=AT)
    await repos.projects.add(project)

    seeded = await repos.judges.defaults()
    assert [(d.kind, d.strictness, d.model_id, d.revision) for d in seeded] == [
        (JudgeKind.TEXT_WIDGET, Strictness.WARN, None, 1),
        (JudgeKind.WIDGET_CODE, Strictness.WARN, None, 1),
    ]
    chosen = await repos.judges.update_defaults(
        seeded[0].model_copy(update={"model_id": model.id, "instructions": "Global"}), 1
    )
    assert (chosen.model_id, chosen.instructions, chosen.revision) == (model.id, "Global", 2)
    with pytest.raises(Conflict):
        await repos.judges.update_defaults(chosen, 1)

    assert await repos.judges.overrides(project.id) == []
    override = JudgeOverride(
        project_id=project.id, kind=JudgeKind.TEXT_WIDGET, strictness=Strictness.BLOCK
    )
    added = await repos.judges.save_override(override, 0)
    assert (added.strictness, added.model_id, added.instructions, added.revision) == (
        Strictness.BLOCK,
        None,
        None,
        1,
    )
    with pytest.raises(Conflict):
        await repos.judges.save_override(override, 0)
    changed = await repos.judges.save_override(
        added.model_copy(update={"strictness": None, "model_id": model.id}), 1
    )
    assert (changed.strictness, changed.model_id, changed.revision) == (None, model.id, 2)
    assert await repos.judges.overrides(project.id) == [changed]

    await repos.models.delete(model.id)

    assert (await repos.judges.defaults())[0].model_id is None
    assert (await repos.judges.overrides(project.id))[0].model_id is None
