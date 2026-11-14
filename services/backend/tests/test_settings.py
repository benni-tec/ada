"""The agent's configuration on the settings page: API keys encrypted under the master key,
the settings service on the memory repositories, and its routes once through the API."""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from cryptography.fernet import Fernet
from dishka import Provider, Scope, provide
from fastapi.testclient import TestClient

from ada.adapters.memory.repositories import (
    MemoryAgentSettingsRepository,
    MemoryLlmModelRepository,
    MemoryLlmProviderRepository,
    MemoryStore,
)
from ada.adapters.secrets.fernet import FernetSecretBox, InvalidMasterKey
from ada.config import Settings
from ada.core.models.agents import ProviderKind
from ada.core.models.errors import Conflict, Invalid, NotConfigured
from ada.core.ports.secrets import SecretBox, SecretUnreadable
from ada.core.services.agents.settings import UNREADABLE_KEY, AgentConfiguration
from ada.entrypoints.http.app import create_app
from fakes import FixedClock
from memory import memory_adapters

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()
API_KEY = "sk-test-0123456789"


# Encryption -------------------------------------------------------------------------------


def test_a_secret_comes_back_from_its_token_and_is_not_in_it() -> None:
    box = FernetSecretBox(KEY)

    token = box.encrypt(API_KEY)

    assert box.available
    assert API_KEY not in token
    assert box.decrypt(token) == API_KEY


def test_another_master_key_cannot_read_a_token() -> None:
    token = FernetSecretBox(KEY).encrypt(API_KEY)

    with pytest.raises(SecretUnreadable):
        FernetSecretBox(OTHER_KEY).decrypt(token)
    with pytest.raises(SecretUnreadable):
        FernetSecretBox(None).decrypt(token)


def test_rotation_encrypts_with_the_first_key_and_reads_with_all() -> None:
    old_token = FernetSecretBox(KEY).encrypt(API_KEY)
    rotated = FernetSecretBox(f"{OTHER_KEY}, {KEY}")

    assert rotated.decrypt(old_token) == API_KEY
    assert FernetSecretBox(OTHER_KEY).decrypt(rotated.encrypt(API_KEY)) == API_KEY


def test_without_a_master_key_nothing_is_available_and_a_bad_one_stops_the_start() -> None:
    assert not FernetSecretBox(None).available
    assert not FernetSecretBox(" ").available
    with pytest.raises(InvalidMasterKey, match="ADA_SECRET_KEY"):
        FernetSecretBox("not-a-key")


def test_the_master_key_comes_from_the_variable_or_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "secret"
    file.write_text(f"{KEY}\n")
    urls = {"database_url": "postgresql+psycopg://x/", "valkey_url": "redis://x"}

    monkeypatch.setenv("ADA_SECRET_KEY_FILE", str(file))
    assert Settings(**urls).master_key() == KEY  # type: ignore[arg-type]
    monkeypatch.setenv("ADA_SECRET_KEY", OTHER_KEY)
    assert Settings(**urls).master_key() == OTHER_KEY  # type: ignore[arg-type]
    monkeypatch.delenv("ADA_SECRET_KEY")
    monkeypatch.delenv("ADA_SECRET_KEY_FILE")
    assert Settings(**urls).master_key() is None  # type: ignore[arg-type]


# The service ------------------------------------------------------------------------------


def service(store: MemoryStore, master_key: str | None = KEY) -> AgentConfiguration:
    return AgentConfiguration(
        MemoryLlmProviderRepository(store),
        MemoryLlmModelRepository(store),
        MemoryAgentSettingsRepository(store),
        FernetSecretBox(master_key),
        FixedClock(),
    )


@pytest.mark.anyio
async def test_models_are_available_when_their_provider_has_the_key_it_needs() -> None:
    settings = service(MemoryStore())
    gemini = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    local = await settings.add_provider("vllm", ProviderKind.OPENAI_COMPATIBLE, "http://h/v1")
    keyless = await settings.add_provider("google", ProviderKind.GEMINI)
    for provider in (gemini, local, keyless):
        await settings.add_model(provider.id, "m/1")

    catalog = await settings.catalog()

    assert gemini.has_api_key and not local.has_api_key
    assert [(m.id, m.available, m.reason) for m in catalog.models] == [
        ("gemini/m/1", True, None),
        ("vllm/m/1", True, None),
        ("google/m/1", False, "The provider google needs an API key"),
    ]
    target = await settings.target("gemini/m/1")
    assert (target.kind, target.model) == (ProviderKind.GEMINI, "m/1")
    assert target.api_key is not None and target.api_key.get_secret_value() == API_KEY
    with pytest.raises(Invalid, match="needs an API key"):
        await settings.target("google/m/1")


@pytest.mark.anyio
async def test_a_key_the_master_key_cannot_read_makes_its_models_unavailable() -> None:
    store = MemoryStore()
    provider = await service(store).add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    await service(store).add_model(provider.id, "flash")

    [model] = (await service(store, OTHER_KEY).catalog()).models

    assert (model.available, model.reason) == (False, UNREADABLE_KEY)
    # Entering it again, without the old one, makes it usable.
    rekeyed = service(store, OTHER_KEY)
    await rekeyed.update_provider(provider.id, provider.revision, api_key=API_KEY)
    assert (await rekeyed.catalog()).models[0].available


@pytest.mark.anyio
async def test_the_session_agent_is_set_and_cleared_with_its_provider() -> None:
    settings = service(MemoryStore())
    provider = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    await settings.add_model(provider.id, "flash")

    view = await settings.set_session_agent("gemini/flash", 1)

    assert view.session_agent == "gemini/flash"
    assert view.models.models[0].purposes == ("session_agent",)
    with pytest.raises(Conflict):
        await settings.set_session_agent(None, 1)
    with pytest.raises(Invalid, match="other/x"):
        await settings.set_session_agent("other/x", view.revision)

    await settings.delete_provider(provider.id)

    after = await settings.view()
    assert (after.session_agent, after.providers, after.models.models) == (None, (), ())


@pytest.mark.anyio
async def test_the_instructions_for_every_project_are_stored_with_the_revision() -> None:
    settings = service(MemoryStore())

    view = await settings.set_instructions("  Cite the page.  ", 1)

    assert (view.instructions, view.revision) == ("Cite the page.", 2)
    assert (await settings.view()).instructions == "Cite the page."
    with pytest.raises(Conflict):
        await settings.set_instructions("Stale", 1)
    assert (await settings.view()).instructions == "Cite the page."


@pytest.mark.anyio
async def test_the_research_agent_falls_back_to_the_session_agent() -> None:
    settings = service(MemoryStore())
    provider = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    await settings.add_model(provider.id, "flash")
    await settings.add_model(provider.id, "pro")
    assert await settings.research_agent() is None

    view = await settings.set_session_agent("gemini/flash", 1)
    assert await settings.research_agent() == "gemini/flash"
    view = await settings.set_research_agent("gemini/pro", view.revision)

    assert (view.research_agent, await settings.research_agent()) == ("gemini/pro", "gemini/pro")
    assert [m.purposes for m in view.models.models] == [("session_agent",), ("research_agent",)]
    with pytest.raises(Invalid, match="other/x"):
        await settings.set_research_agent("other/x", view.revision)


@pytest.mark.anyio
async def test_a_deleted_model_is_not_selected_again_when_added_back() -> None:
    store = MemoryStore()
    settings = service(store)
    provider = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    model = await settings.add_model(provider.id, "flash")
    repository = MemoryAgentSettingsRepository(store)
    chosen = await repository.get()
    await repository.update(
        chosen.model_copy(update={"session_agent": model.id, "research_agent": model.id}),
        chosen.revision,
    )

    await settings.delete_model(model.id)
    await settings.add_model(provider.id, "flash")

    after = await repository.get()
    assert (after.session_agent, after.research_agent) == (None, None)


@pytest.mark.anyio
async def test_a_cleared_provider_renames_its_models_and_the_session_agent() -> None:
    settings = service(MemoryStore())
    provider = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    await settings.add_model(provider.id, "flash")
    await settings.set_session_agent("gemini/flash", 1)

    await settings.update_provider(provider.id, provider.revision, name="google")

    assert (await settings.catalog()).session_agent == "google/flash"


@pytest.mark.anyio
async def test_providers_are_checked() -> None:
    settings = service(MemoryStore())
    await settings.add_provider("gemini", ProviderKind.GEMINI)

    with pytest.raises(Invalid, match="lowercase"):
        await settings.add_provider("Gemini Pro", ProviderKind.GEMINI)
    with pytest.raises(Invalid, match="already"):
        await settings.add_provider("gemini", ProviderKind.GEMINI)
    with pytest.raises(Invalid, match="base URL"):
        await settings.add_provider("vllm", ProviderKind.OPENAI_COMPATIBLE)


@pytest.mark.anyio
async def test_without_a_master_key_a_key_cannot_be_stored() -> None:
    settings = service(MemoryStore(), master_key=None)

    with pytest.raises(NotConfigured, match="ADA_SECRET_KEY"):
        await settings.add_provider("gemini", ProviderKind.GEMINI, api_key=API_KEY)
    # Everything else works.
    provider = await settings.add_provider("gemini", ProviderKind.GEMINI, api_key="")
    assert not provider.has_api_key
    assert not (await settings.view()).secrets_available


# The routes -------------------------------------------------------------------------------


class MasterKey(Provider):
    scope = Scope.APP

    @provide
    def secrets(self) -> SecretBox:
        return FernetSecretBox(KEY)


@pytest.fixture
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    app = create_app(unreachable_settings, *memory_adapters(), MasterKey())
    with TestClient(app) as client:
        yield client


def test_the_settings_routes_configure_the_agent_and_never_return_a_key(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/settings/llm-providers",
        json={"name": "gemini", "kind": "gemini", "api_key": API_KEY},
    )
    provider = created.json()
    model = client.post(
        "/api/settings/llm-models", json={"provider_id": provider["id"], "model": "flash"}
    )
    settings = client.get("/api/settings/agent").json()
    chosen = client.put(
        "/api/settings/session-agent",
        json={"model_id": "gemini/flash", "expected_revision": settings["revision"]},
    )
    stale = client.patch(
        f"/api/settings/llm-providers/{provider['id']}",
        json={"expected_revision": provider["revision"] + 1, "api_key": "sk-other"},
    )
    cleared = client.patch(
        f"/api/settings/llm-providers/{provider['id']}",
        json={"expected_revision": provider["revision"], "base_url": None},
    )
    models = client.get("/api/llm/models")

    responses = [created, model, chosen, stale, cleared, models]
    assert [r.status_code for r in responses] == [201, 201, 200, 409, 200, 200]
    assert provider["has_api_key"] is True
    assert model.json()["id"] == "gemini/flash" and model.json()["available"] is True
    assert settings["secrets_available"] is True and settings["session_agent"] is None
    assert chosen.json()["session_agent"] == "gemini/flash"
    assert stale.json()["revision"] == provider["revision"]
    assert models.json()["session_agent"] == "gemini/flash"
    assert all(API_KEY not in r.text and "sk-other" not in r.text for r in responses)

    deleted = client.delete(f"/api/settings/llm-models/{quote('gemini/flash', safe='')}")

    assert deleted.status_code == 204
    assert client.get("/api/settings/agent").json()["session_agent"] is None
    assert client.delete(f"/api/settings/llm-providers/{provider['id']}").status_code == 204
    assert client.get("/api/settings/agent").json()["providers"] == []


def test_instructions_are_revision_checked_and_the_web_settings_read_the_configuration(
    client: TestClient,
) -> None:
    revision = client.get("/api/settings/agent").json()["revision"]
    saved = client.put(
        "/api/settings/agent-instructions",
        json={"instructions": "Answer in English.", "expected_revision": revision},
    )
    stale = client.put(
        "/api/settings/agent-instructions",
        json={"instructions": "Lost", "expected_revision": revision},
    )
    project = client.post("/api/projects", json={"name": "Equal Care"}).json()
    told = client.patch(
        f"/api/projects/{project['id']}",
        json={"agent_instructions": "Cite the page.", "expected_revision": project["revision"]},
    )
    stale_project = client.patch(
        f"/api/projects/{project['id']}",
        json={"agent_instructions": "Lost", "expected_revision": project["revision"]},
    )
    web = client.get("/api/settings/web")

    codes = [r.status_code for r in (saved, stale, told, stale_project, web)]
    assert codes == [200, 409, 200, 409, 200]
    assert client.get("/api/settings/agent").json()["instructions"] == "Answer in English."
    assert project["agent_instructions"] == ""
    assert told.json()["agent_instructions"] == "Cite the page."
    assert told.json()["name"] == "Equal Care"
    assert web.json() == {
        "context_dev_configured": False,
        "exa_configured": False,
        "watching_configured": False,
        "daily_credit_limit": 300,
    }


def test_without_a_master_key_storing_a_key_is_a_conflict(unreachable_settings: Settings) -> None:
    with TestClient(create_app(unreachable_settings, *memory_adapters())) as client:
        response = client.post(
            "/api/settings/llm-providers",
            json={"name": "gemini", "kind": "gemini", "api_key": API_KEY},
        )

        assert response.status_code == 409
        assert "ADA_SECRET_KEY" in response.json()["detail"]
        assert client.get("/api/settings/agent").json()["secrets_available"] is False
