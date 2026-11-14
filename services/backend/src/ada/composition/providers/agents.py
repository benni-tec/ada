from dishka import Provider, Scope, provide

from ada.adapters.llm.config import ConfiguredModels, LlmsConfig, load_llms_config
from ada.adapters.llm.runtime import PydanticAiRuntime
from ada.config import Settings
from ada.core.ports.agents import AgentRuntime, LanguageModels
from ada.core.services.agents.service import AgentTurns
from ada.core.services.ports.agents import AgentTurnService


class AgentProvider(Provider):
    """The in-platform agent: the models file, pydantic-ai to run it, and its turns. Its
    tools are not bound here: whoever runs a turn passes them (the worker serves the MCP
    tools in process)."""

    @provide(scope=Scope.APP)
    def llms_config(self, settings: Settings) -> LlmsConfig:
        # Read once per process, with the keys of that moment's environment.
        return load_llms_config(settings.llms_config)

    @provide(scope=Scope.APP)
    def language_models(self, config: LlmsConfig) -> LanguageModels:
        return ConfiguredModels(config)

    @provide(scope=Scope.APP)
    def runtime(self, config: LlmsConfig) -> AgentRuntime:
        return PydanticAiRuntime(config)

    turns = provide(AgentTurns, provides=AgentTurnService, scope=Scope.REQUEST)


provider = AgentProvider()
