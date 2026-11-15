"""Runs a turn with pydantic-ai: the model the turn's request names, the turn's tools, and
the run's events turned into the parts of the turn as they happen."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, ModelRetry, Tool
from pydantic_ai.exceptions import (
    AgentRunError,
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    UserPromptPart,
)
from pydantic_ai.messages import TextPart as AiTextPart
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_core import to_jsonable_python

from ada.core.models.agents import (
    HistoryMessage,
    ModelTarget,
    ProviderKind,
    ReasoningPart,
    TextPart,
    ToolPart,
    ToolSpec,
    ToolState,
    TurnRequest,
    TurnStatus,
)
from ada.core.ports.agents import (
    AgentFailed,
    AgentRuntime,
    AgentTools,
    ToolCallFailed,
    TurnSink,
)

# How often the model may correct one tool's call after the tool refused it; a model that
# keeps getting it wrong ends the turn rather than spending its steps.
TOOL_RETRIES = 3

type ModelFactory = Callable[[str], Model]


class PydanticAiRuntime(AgentRuntime):
    """Calls the model of the request's target. `model_factory` replaces the providers,
    e.g. with pydantic-ai's FunctionModel in tests, so nothing calls a provider."""

    def __init__(self, model_factory: ModelFactory | None = None) -> None:
        self.model_factory = model_factory

    async def run(self, request: TurnRequest, tools: AgentTools, sink: TurnSink) -> TurnStatus:
        agent = Agent(
            self._model(request),
            output_type=str,
            tools=[_tool(spec, tools) for spec in tools.specs()],
            retries={"tools": TOOL_RETRIES},
        )
        parts = _Parts(sink)
        try:
            async with agent.iter(
                request.prompt,
                message_history=_history(request.history),
                instructions=request.instructions,
                usage_limits=UsageLimits(request_limit=request.max_steps),
            ) as run:
                async for node in run:
                    if Agent.is_model_request_node(node):
                        parts.new_response()
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                await parts.model_event(event)
                    elif Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as stream:
                            async for event in stream:
                                await parts.tool_event(event)
                    # Between two steps: the turn's parts are stored, and a cancel is seen.
                    if await sink.checkpoint():
                        return TurnStatus.CANCELLED
        except UsageLimitExceeded as error:
            raise AgentFailed(
                f"The agent did not finish within {request.max_steps} steps"
            ) from error
        except ModelAuthenticationError:
            # Authentication bodies can echo credentials (even masked fragments).
            raise AgentFailed(
                "The model provider refused the key. Update this provider's API key in Settings."
            ) from None
        except ModelConnectionError as error:
            raise AgentFailed(f"The model provider could not be reached: {error}") from error
        except ModelAPIError as error:
            raise AgentFailed(f"The model provider answered with an error: {error}") from error
        except UnexpectedModelBehavior as error:
            raise AgentFailed(f"The model did not answer as expected: {error}") from error
        except AgentRunError as error:
            raise AgentFailed(f"The agent run failed: {error}") from error
        return TurnStatus.DONE

    def _model(self, request: TurnRequest) -> Model:
        if self.model_factory is not None:
            return self.model_factory(request.model)
        return provider_model(request.target)


def provider_model(target: ModelTarget) -> Model:
    """The pydantic-ai model for a target. Builds clients only; nothing is sent until a
    turn runs."""
    key = target.api_key.get_secret_value() if target.api_key is not None else None
    match target.kind:
        case ProviderKind.OPENAI_COMPATIBLE:
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            # The client insists on a key; an endpoint without one ignores whatever it gets.
            provider = OpenAIProvider(base_url=target.base_url, api_key=key or "none")
            return OpenAIChatModel(target.model, provider=provider)
        case ProviderKind.GEMINI:
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider

            return GoogleModel(
                target.model, provider=GoogleProvider(api_key=key, base_url=target.base_url)
            )


def _tool(spec: ToolSpec, tools: AgentTools) -> Tool[Any]:
    async def call(**arguments: Any) -> Any:
        try:
            return await tools.call(spec.name, arguments)
        except ToolCallFailed as error:
            # Back to the model, which may correct the call; counts against TOOL_RETRIES.
            raise ModelRetry(str(error)) from error

    # One at a time: a widget made in the same step as its operator must find it.
    return Tool.from_schema(
        call,
        name=spec.name,
        description=spec.description,
        json_schema=spec.input_schema,
        sequential=True,
    )


def _history(history: tuple[HistoryMessage, ...]) -> list[ModelMessage]:
    return [
        ModelRequest(parts=[UserPromptPart(content=message.text)])
        if message.role == "user"
        else ModelResponse(parts=[AiTextPart(content=message.text)])
        for message in history
    ]


@dataclass
class _Streamed:
    """A text or reasoning part of the current model response, as far as it has come."""

    reasoning: bool
    text: str = ""
    # The turn's index once the part has any text; empty parts are not shown.
    index: int | None = None


class _Parts:
    """Turns pydantic-ai's events into the turn's parts, in the order they happen."""

    def __init__(self, sink: TurnSink) -> None:
        self.sink = sink
        # By the response's own part index, which starts at 0 for every model request.
        self.streamed: dict[int, _Streamed] = {}
        # By tool call id: the turn's index and the part.
        self.tools: dict[str, tuple[int, ToolPart]] = {}

    def new_response(self) -> None:
        self.streamed = {}

    async def model_event(self, event: Any) -> None:
        match event:
            case PartStartEvent(index=index, part=AiTextPart(content=content)):
                await self._set(index, content, reasoning=False)
            case PartStartEvent(index=index, part=ThinkingPart(content=content)):
                await self._set(index, content, reasoning=True)
            case PartDeltaEvent(index=index, delta=TextPartDelta(content_delta=delta)):
                await self._grow(index, delta)
            case PartDeltaEvent(index=index, delta=ThinkingPartDelta(content_delta=delta)):
                await self._grow(index, delta or "")
            case PartEndEvent(
                index=index, part=AiTextPart(content=content) | ThinkingPart(content=content)
            ):
                streamed = self.streamed.get(index)
                if streamed is not None and streamed.text != content:
                    await self._set(index, content, reasoning=streamed.reasoning)
            case _:
                # Tool calls are shown once complete, from the tool events.
                pass

    async def tool_event(self, event: Any) -> None:
        match event:
            case FunctionToolCallEvent(part=call):
                part = ToolPart(
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    state=ToolState.INPUT_AVAILABLE,
                    input=call.args_as_dict(),
                )
                self.tools[call.tool_call_id] = (await self.sink.add(part), part)
            case FunctionToolResultEvent(part=result):
                found = self.tools.get(result.tool_call_id)
                if found is None:
                    return
                index, part = found
                if result.outcome == "success":
                    done = part.model_copy(
                        update={
                            "state": ToolState.OUTPUT_AVAILABLE,
                            "output": to_jsonable_python(result.content, fallback=str),
                        }
                    )
                else:
                    done = part.model_copy(
                        update={
                            "state": ToolState.OUTPUT_ERROR,
                            "error_text": _text(result.content),
                        }
                    )
                self.tools[result.tool_call_id] = (index, done)
                await self.sink.replace(index, done)
            case _:
                pass

    async def _set(self, index: int, text: str, reasoning: bool) -> None:
        streamed = self.streamed.get(index)
        if streamed is None or streamed.reasoning != reasoning:
            # A new part, or one that replaces what started at this index.
            previous = streamed.index if streamed is not None else None
            streamed = self.streamed[index] = _Streamed(reasoning=reasoning, index=previous)
        streamed.text = text
        await self._show(streamed)

    async def _grow(self, index: int, delta: str) -> None:
        streamed = self.streamed.get(index)
        if streamed is None or not delta:
            return
        streamed.text += delta
        await self._show(streamed)

    async def _show(self, streamed: _Streamed) -> None:
        if not streamed.text:
            return
        part = (
            ReasoningPart(text=streamed.text)
            if streamed.reasoning
            else TextPart(text=streamed.text)
        )
        if streamed.index is None:
            streamed.index = await self.sink.add(part)
        else:
            await self.sink.replace(streamed.index, part)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return str(to_jsonable_python(content, fallback=str))
