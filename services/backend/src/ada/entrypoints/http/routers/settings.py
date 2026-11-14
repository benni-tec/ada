"""The settings page's routes for the agent: providers, their models, the session agent
and the research agent. Instance-wide, shared by all projects. No response ever carries
an API key."""

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, status

from ada.core.models.agents import AgentSettingsView, LlmProvider, ModelInfo, ProviderKind
from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.services.ports.agents import AgentSettingsService
from ada.entrypoints.http.requests import Request

router = APIRouter(route_class=DishkaRoute, tags=["settings"])


class NewProvider(Request):
    # A slug: lowercase letters, digits and dashes. The first half of its models' ids.
    name: str
    kind: ProviderKind
    # Required for openai-compatible.
    base_url: str | None = None
    # Stored encrypted; empty or null for none. Refused (409) without a master key.
    api_key: str | None = None


class ProviderChange(Request):
    """Fields left out stay as they are. `base_url` and `api_key` may be emptied: null or
    "" clears them. A new key never needs the old one."""

    expected_revision: int
    name: str | None = None
    kind: ProviderKind | None = None
    base_url: str | None = None
    api_key: str | None = None

    def given[T](self, field: str, value: T) -> Change[T]:
        return value if field in self.model_fields_set else UNCHANGED


class NewModel(Request):
    provider_id: Id
    # The provider's name for the model, e.g. "gemini-2.5-flash".
    model: str


class SessionAgentChoice(Request):
    # A model id ("<provider>/<model>"), or null: no session agent, or, for the research
    # agent, the session agent's model.
    model_id: str | None
    expected_revision: int


@router.get("/settings/agent")
async def get_agent_settings(service: FromDishka[AgentSettingsService]) -> AgentSettingsView:
    """Providers (with `has_api_key`, never the key), the models with their availability,
    the session agent, whether keys can be stored (`secrets_available`), and the revision
    for setting the session agent."""
    return await service.view()


@router.post("/settings/llm-providers", status_code=status.HTTP_201_CREATED)
async def add_provider(body: NewProvider, service: FromDishka[AgentSettingsService]) -> LlmProvider:
    return await service.add_provider(body.name, body.kind, body.base_url, body.api_key)


@router.patch("/settings/llm-providers/{provider_id}")
async def update_provider(
    provider_id: Id, body: ProviderChange, service: FromDishka[AgentSettingsService]
) -> LlmProvider:
    return await service.update_provider(
        provider_id,
        body.expected_revision,
        name=body.name,
        kind=body.kind,
        base_url=body.given("base_url", body.base_url),
        api_key=body.given("api_key", body.api_key),
    )


@router.delete("/settings/llm-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: Id, service: FromDishka[AgentSettingsService]) -> None:
    """With its models; the session agent is cleared when it was one of them."""
    await service.delete_provider(provider_id)


@router.post("/settings/llm-models", status_code=status.HTTP_201_CREATED)
async def add_model(body: NewModel, service: FromDishka[AgentSettingsService]) -> ModelInfo:
    return await service.add_model(body.provider_id, body.model)


# `path`: the id is "<provider>/<model>", sent URL-encoded, and arrives decoded.
@router.delete("/settings/llm-models/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: str, service: FromDishka[AgentSettingsService]) -> None:
    """The session agent is cleared when it was this model."""
    await service.delete_model(model_id)


@router.put("/settings/session-agent")
async def set_session_agent(
    body: SessionAgentChoice, service: FromDishka[AgentSettingsService]
) -> AgentSettingsView:
    return await service.set_session_agent(body.model_id, body.expected_revision)


@router.put("/settings/research-agent")
async def set_research_agent(
    body: SessionAgentChoice, service: FromDishka[AgentSettingsService]
) -> AgentSettingsView:
    """The model of research sessions; null falls back to the session agent's."""
    return await service.set_research_agent(body.model_id, body.expected_revision)
