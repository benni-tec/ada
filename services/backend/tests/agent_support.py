"""The in-platform agent in tests: a scripted model (pydantic-ai's FunctionModel) in place
of every provider, and a configuration with one session agent, stored through the settings
service with a master key of the test's own. Nothing calls a provider."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet
from dishka import AsyncContainer, Provider, Scope, provide
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ada.adapters.llm.runtime import PydanticAiRuntime
from ada.adapters.secrets.fernet import FernetSecretBox
from ada.core.models.agents import AgentTurn, ProviderKind
from ada.core.models.base import Id
from ada.core.ports.agents import AgentRuntime
from ada.core.ports.secrets import SecretBox
from ada.core.services.ports.agents import AgentSettingsService, AgentTurnService
from ada.entrypoints.mcp.agent import InProcessToolbox

MODEL = "test/scripted"
AGENT = {"kind": "agent", "name": MODEL}

type Step = Callable[[list[ModelMessage], AgentInfo], AsyncIterator[Any]]


# The master key of every test app with the agent.
MASTER_KEY = Fernet.generate_key().decode()


@dataclass(frozen=True)
class AgentSetup:
    """One provider, "test", with one model that is the session agent."""

    key: str | None = "secret"
    model: str = MODEL
    kind: ProviderKind = ProviderKind.OPENAI_COMPATIBLE


def config(
    key: str | None = "secret",
    model: str = MODEL,
    kind: ProviderKind = ProviderKind.OPENAI_COMPATIBLE,
) -> AgentSetup:
    """A configuration with one provider whose key is stored (or not)."""
    return AgentSetup(key=key, model=model, kind=kind)


async def configure(container: AsyncContainer, setup: AgentSetup | None) -> None:
    """Store the setup through the settings service, as the Settings page would."""
    if setup is None:
        return
    provider_name, _, model = setup.model.partition("/")
    async with container() as request:
        service = await request.get(AgentSettingsService)
        provider = await service.add_provider(
            provider_name, setup.kind, "http://127.0.0.1:1/v1", setup.key
        )
        await service.add_model(provider.id, model)
        settings = await service.view()
        await service.set_session_agent(setup.model, settings.revision)


@dataclass
class Script:
    """The model's answers, one step per model request, in order. Records what it was sent."""

    steps: list[Step] = field(default_factory=list)
    calls: list[tuple[list[ModelMessage], AgentInfo]] = field(default_factory=list)
    # Run before each step, e.g. to cancel the turn while it runs.
    before_step: Callable[[int], Any] | None = None

    def then(self, *steps: Step) -> Script:
        self.steps.extend(steps)
        return self

    def model(self) -> Model:
        return FunctionModel(stream_function=self._stream, model_name="scripted")

    async def _stream(self, messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[Any]:
        self.calls.append((list(messages), info))
        if self.before_step is not None:
            result = self.before_step(len(self.calls))
            if hasattr(result, "__await__"):
                await result
        if not self.steps:
            raise AssertionError("The model was asked more often than scripted")
        async for item in self.steps.pop(0)(messages, info):
            yield item


def call(
    name: str, arguments: Callable[[list[ModelMessage]], dict[str, Any]] | dict[str, Any]
) -> Step:
    """A step that calls one tool. `arguments` may be worked out from the messages so far,
    e.g. from an earlier tool's result."""

    async def step(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[Any]:
        values = arguments(messages) if callable(arguments) else arguments
        call_id = f"call_{name}_{len(messages)}"
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(values), tool_call_id=call_id)}

    return step


def say(*chunks: str) -> Step:
    """A step that answers with text, streamed in these chunks."""

    async def step(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[Any]:
        for chunk in chunks:
            yield chunk

    return step


def fail(error: Exception) -> Step:
    async def step(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[Any]:
        raise error
        yield  # pragma: no cover - makes this an async generator

    return step


def returned(messages: list[ModelMessage], tool: str) -> Any:
    """What the latest call of `tool` returned to the model."""
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart) and part.tool_name == tool:
                    return part.content
    raise AssertionError(f"{tool} was not called")


class AgentOverrides(Provider):
    """A master key of the test's own, and pydantic-ai on the scripted model in place of the
    providers. The configuration itself is stored with `configure`."""

    scope = Scope.APP

    def __init__(self, script: Script) -> None:
        super().__init__()
        self.script = script
        # Replaces the scripted model, e.g. with a real client of an unreachable provider.
        self.factory: Callable[[str], Model] | None = None

    @provide
    def secrets(self) -> SecretBox:
        return FernetSecretBox(MASTER_KEY)

    @provide
    def runtime(self) -> AgentRuntime:
        def model(model_id: str) -> Model:
            return self.factory(model_id) if self.factory else self.script.model()

        return PydanticAiRuntime(model_factory=model)


async def run_turn(container: AsyncContainer, turn_id: Id) -> AgentTurn:
    """What the worker's run_turn task does, on this container."""
    async with container() as request:
        service = await request.get(AgentTurnService)
        return await service.run(turn_id, InProcessToolbox(container))
