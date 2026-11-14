"""The agent's configuration: model providers, their models, the session agent. Shared by
all projects.

API keys are encrypted with the SecretBox before they are stored and decrypted only to
build a ModelTarget for a turn that runs. Nothing returned here carries one.
"""

import re
from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.agents import (
    PROVIDER_NAME,
    RESEARCH_AGENT,
    SESSION_AGENT,
    AgentSettings,
    AgentSettingsView,
    LlmModel,
    LlmProvider,
    ModelInfo,
    ModelList,
    ModelTarget,
    ProviderKind,
)
from ada.core.models.base import UNCHANGED, Change, Id
from ada.core.models.errors import Invalid, NotConfigured, NotFound
from ada.core.ports.agents import LanguageModels
from ada.core.ports.repositories import (
    AgentSettingsRepository,
    LlmModelRepository,
    LlmProviderRepository,
)
from ada.core.ports.secrets import SecretBox, SecretUnreadable
from ada.core.ports.system import Clock
from ada.core.services.ports.agents import AgentSettingsService

UNREADABLE_KEY = "The stored key cannot be decrypted; enter it again"
NO_MASTER_KEY = (
    "API keys cannot be stored: no master key is set. Set ADA_SECRET_KEY (or "
    "ADA_SECRET_KEY_FILE) for the backend and the worker, then restart them"
)


class AgentConfiguration(AgentSettingsService, LanguageModels):
    def __init__(
        self,
        providers: LlmProviderRepository,
        models: LlmModelRepository,
        settings: AgentSettingsRepository,
        secrets: SecretBox,
        clock: Clock,
    ) -> None:
        self.providers = providers
        self.models = models
        self.settings = settings
        self.secrets = secrets
        self.clock = clock

    # The settings page ------------------------------------------------------------------

    async def view(self) -> AgentSettingsView:
        settings = await self.settings.get()
        providers = await self.providers.list()
        return AgentSettingsView(
            providers=tuple(providers),
            models=await self._catalog(providers, settings),
            session_agent=settings.session_agent,
            research_agent=settings.research_agent,
            secrets_available=self.secrets.available,
            revision=settings.revision,
        )

    async def add_provider(
        self, name: str, kind: ProviderKind, base_url: str | None = None, api_key: str | None = None
    ) -> LlmProvider:
        provider = LlmProvider(
            id=uuid7(),
            name=name.strip(),
            kind=kind,
            base_url=_text(base_url),
            created_at=self.clock.now(),
        )
        await self._check(provider)
        return await self.providers.add(provider, self._encrypted(_text(api_key)))

    async def update_provider(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        kind: ProviderKind | None = None,
        base_url: Change[str | None] = UNCHANGED,
        api_key: Change[str | None] = UNCHANGED,
    ) -> LlmProvider:
        provider = await self.providers.get(id)
        changes: dict[str, object] = {}
        if name is not None:
            changes["name"] = name.strip()
        if kind is not None:
            changes["kind"] = kind
        if base_url is not UNCHANGED:
            changes["base_url"] = _text(base_url)
        updated = provider.model_copy(update=changes)
        await self._check(updated)
        key: Change[str | None] = UNCHANGED
        if api_key is not UNCHANGED:
            key = self._encrypted(_text(api_key))
        return await self.providers.update(updated, expected_revision, key)

    async def delete_provider(self, id: Id) -> None:
        await self.providers.delete(id)

    async def add_model(self, provider_id: Id, model: str) -> ModelInfo:
        provider = await self.providers.get(provider_id)
        name = model.strip()
        if not name:
            raise Invalid("A model needs a name")
        if any(
            known.provider_id == provider_id and known.model == name
            for known in await self.models.list()
        ):
            raise Invalid(f"The provider {provider.name} has a model {name!r} already")
        added = await self.models.add(
            LlmModel(id="", provider_id=provider_id, model=name, created_at=self.clock.now())
        )
        settings = await self.settings.get()
        return await self._info(provider, added, settings)

    async def delete_model(self, id: str) -> None:
        await self.models.delete(id)

    async def set_session_agent(
        self, model_id: str | None, expected_revision: int
    ) -> AgentSettingsView:
        if model_id is not None:
            try:
                await self.models.get(model_id)
            except NotFound:
                raise Invalid(f"No model {model_id!r} is configured") from None
        settings = await self.settings.get()
        await self.settings.update(
            settings.model_copy(update={"session_agent": model_id}), expected_revision
        )
        return await self.view()

    # LanguageModels ---------------------------------------------------------------------

    async def catalog(self) -> ModelList:
        settings = await self.settings.get()
        return await self._catalog(await self.providers.list(), settings)

    async def target(self, model_id: str) -> ModelTarget:
        try:
            model = await self.models.get(model_id)
        except NotFound:
            raise Invalid(f"No model {model_id!r} is configured") from None
        provider = await self.providers.get(model.provider_id)
        key, reason = await self._key(provider)
        if reason is not None:
            raise Invalid(reason)
        return ModelTarget(
            model_id=model.id,
            kind=provider.kind,
            base_url=provider.base_url,
            model=model.model,
            api_key=key,
        )

    # Helpers ----------------------------------------------------------------------------

    async def _catalog(
        self, providers: Sequence[LlmProvider], settings: AgentSettings
    ) -> ModelList:
        by_id = {provider.id: provider for provider in providers}
        infos = [
            await self._info(by_id[model.provider_id], model, settings)
            for model in await self.models.list()
        ]
        return ModelList(
            models=tuple(infos),
            session_agent=settings.session_agent,
            research_agent=settings.research_agent,
        )

    async def _info(
        self, provider: LlmProvider, model: LlmModel, settings: AgentSettings
    ) -> ModelInfo:
        _, reason = await self._key(provider)
        return ModelInfo(
            id=model.id,
            provider=provider.name,
            model=model.model,
            purposes=tuple(
                purpose
                for purpose, chosen in (
                    (SESSION_AGENT, settings.session_agent),
                    (RESEARCH_AGENT, settings.research_agent),
                )
                if model.id == chosen
            ),
            available=reason is None,
            reason=reason,
        )

    async def _key(self, provider: LlmProvider) -> tuple[str | None, str | None]:
        """The provider's key and, when it cannot be used, why."""
        if not provider.has_api_key:
            if provider.kind is ProviderKind.GEMINI:
                return None, f"The provider {provider.name} needs an API key"
            # An openai-compatible endpoint may need none, e.g. a local vLLM.
            return None, None
        token = await self.providers.api_key(provider.id)
        assert token is not None
        try:
            return self.secrets.decrypt(token), None
        except SecretUnreadable:
            return None, UNREADABLE_KEY

    def _encrypted(self, api_key: str | None) -> str | None:
        if api_key is None:
            return None
        if not self.secrets.available:
            raise NotConfigured(NO_MASTER_KEY)
        return self.secrets.encrypt(api_key)

    async def _check(self, provider: LlmProvider) -> None:
        if not re.fullmatch(PROVIDER_NAME, provider.name):
            raise Invalid(
                f"A provider's name is lowercase letters, digits and dashes, not {provider.name!r}"
            )
        if provider.kind is ProviderKind.OPENAI_COMPATIBLE and not provider.base_url:
            raise Invalid("An openai-compatible provider needs a base URL")
        for other in await self.providers.list():
            if other.name == provider.name and other.id != provider.id:
                raise Invalid(f"There is a provider named {provider.name} already")


def _text(value: str | None) -> str | None:
    """Empty is none."""
    if value is None:
        return None
    return value.strip() or None
