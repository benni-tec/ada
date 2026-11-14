from dishka import AnyOf, Provider, Scope, provide

from ada.adapters.llm.runtime import PydanticAiRuntime
from ada.adapters.secrets.fernet import FernetSecretBox
from ada.config import Settings
from ada.core.models.agents import ResearchLimits
from ada.core.ports.agents import AgentRuntime, LanguageModels
from ada.core.ports.secrets import SecretBox
from ada.core.services.agents.research import Research
from ada.core.services.agents.service import AgentTurns
from ada.core.services.agents.settings import AgentConfiguration
from ada.core.services.ports.agents import (
    AgentSettingsService,
    AgentTurnService,
    ResearchService,
)


class AgentProvider(Provider):
    """The in-platform agent: its configuration in the database (keys encrypted with the
    master key), pydantic-ai to run it, and its turns. Its tools are not bound here:
    whoever runs a turn passes them (the worker serves the MCP tools in process)."""

    @provide(scope=Scope.APP)
    def secrets(self, settings: Settings) -> SecretBox:
        # A master key that is set but malformed stops the start (InvalidMasterKey).
        return FernetSecretBox(settings.master_key())

    @provide(scope=Scope.APP)
    def runtime(self) -> AgentRuntime:
        return PydanticAiRuntime()

    # One service: the settings page's use cases, and the catalog the turns read.
    configuration = provide(
        AgentConfiguration,
        provides=AnyOf[AgentSettingsService, LanguageModels],
        scope=Scope.REQUEST,
    )

    turns = provide(AgentTurns, provides=AgentTurnService, scope=Scope.REQUEST)

    @provide(scope=Scope.APP)
    def research_limits(self, settings: Settings) -> ResearchLimits:
        return ResearchLimits(web_calls=settings.research_web_calls)

    research = provide(Research, provides=ResearchService, scope=Scope.REQUEST)


provider = AgentProvider()
