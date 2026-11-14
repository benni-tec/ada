"""The agent inside the platform: the models it may use, and its turns.

Providers, their models and which model runs sessions are configured in the platform and
shared by all projects. A provider's API key is stored encrypted and is never part of any
model here except ModelTarget, which only the runtime is given.

A turn is the agent's answer to one message of a session. It is stored as parts in the
order they happened (reasoning, tool calls with their arguments and results, the data
sources it read, text), the shape the frontend's Trace component renders.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr

from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.sessions import SessionEntry

# What a configured model is for. One for now; the operators of later waves add theirs.
SESSION_AGENT = "session_agent"
RESEARCH_AGENT = "research_agent"

# A provider's name: the first half of its models' ids.
PROVIDER_NAME = r"^[a-z0-9-]+$"


class ProviderKind(StrEnum):
    # The OpenAI chat completions API, which most providers speak: Gemini's OpenAI
    # endpoint, NVIDIA NIM, OpenAI itself, vLLM.
    OPENAI_COMPATIBLE = "openai-compatible"
    # Google's own Gemini API.
    GEMINI = "gemini"


class LlmProvider(DomainModel):
    """Where models are served. Its API key is stored encrypted beside it and never leaves
    the platform: `has_api_key` is all anyone is told."""

    id: Id
    # A slug, unique: "<name>/<model>" is the id of each of its models.
    name: str
    kind: ProviderKind
    # Required for openai-compatible; Google's default endpoint when left out for gemini.
    base_url: str | None = None
    has_api_key: bool = False
    created_at: datetime
    revision: int = 1


class LlmModel(DomainModel):
    """A model of a provider that the platform may use."""

    # "<provider name>/<model>", e.g. "gemini/gemini-2.5-flash". Follows a renamed provider.
    id: str
    provider_id: Id
    # The provider's name for it; may contain slashes.
    model: str
    created_at: datetime


class AgentSettings(DomainModel):
    """The platform's one record of which model does what."""

    # The model id that answers messages in sessions and dashboard panels; None without
    # one, and cleared when its model or provider is deleted.
    session_agent: str | None = None
    # The model id that runs research sessions; None without one, cleared likewise.
    research_agent: str | None = None
    revision: int = 1


class ModelInfo(DomainModel):
    """A configured model, as the catalog shows it. Its key is never part of it."""

    # "<provider>/<model>", e.g. "gemini/gemini-2.5-flash".
    id: str
    provider: str
    model: str
    # What it is used for, e.g. "session_agent" or "research_agent".
    purposes: tuple[str, ...] = ()
    # False when it cannot be used, e.g. its provider needs a key and has none; `reason`
    # says why.
    available: bool
    reason: str | None = None


class ModelList(DomainModel):
    models: tuple[ModelInfo, ...] = ()
    # The model that answers messages in sessions and dashboard panels; None without one.
    session_agent: str | None = None
    research_agent: str | None = None


class AgentSettingsView(DomainModel):
    """Everything the settings page shows about the agent, in one read."""

    providers: tuple[LlmProvider, ...] = ()
    models: ModelList = ModelList()
    session_agent: str | None = None
    research_agent: str | None = None
    # False when no master key is set (ADA_SECRET_KEY): API keys cannot be stored.
    secrets_available: bool
    # The revision of AgentSettings, for setting the session agent.
    revision: int


class ModelTarget(DomainModel):
    """Everything the runtime needs to call one model, the key included. Built for a turn
    when it runs, never stored and never returned by the API."""

    model_id: str
    kind: ProviderKind
    base_url: str | None = None
    model: str
    # None for a provider without a key, e.g. a local vLLM.
    api_key: SecretStr | None = None


class TurnStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = frozenset({TurnStatus.DONE, TurnStatus.FAILED, TurnStatus.CANCELLED})


class ReasoningPart(DomainModel):
    type: Literal["reasoning"] = "reasoning"
    text: str


class ToolState(StrEnum):
    # The call is made; no result yet.
    INPUT_AVAILABLE = "input-available"
    OUTPUT_AVAILABLE = "output-available"
    OUTPUT_ERROR = "output-error"


class ToolPart(DomainModel):
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    state: ToolState
    input: JsonObject = {}
    output: Any = None
    error_text: str | None = None


class TextPart(DomainModel):
    type: Literal["text"] = "text"
    text: str


class SourcePart(DomainModel):
    """A data source the agent read, so the answer shows where its numbers come from."""

    type: Literal["source"] = "source"
    source_id: Id
    title: str
    url: str | None = None


type TurnPart = Annotated[
    ReasoningPart | ToolPart | TextPart | SourcePart, Field(discriminator="type")
]


class AgentTurn(DomainModel):
    """The agent's answer to one message. Written by the worker as it goes; no revision,
    since nobody else edits it (a cancel request is a flag of its own)."""

    id: Id
    session_id: Id
    # The message it answers.
    prompt_entry_id: Id
    # The id of the model that answers ("<provider>/<model>").
    model: str
    status: TurnStatus = TurnStatus.QUEUED
    parts: tuple[TurnPart, ...] = ()
    # Why it failed, readable by a person.
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class PostedMessage(DomainModel):
    entry: SessionEntry
    # None when no session agent is configured.
    turn: AgentTurn | None = None


class HistoryMessage(DomainModel):
    """An earlier message of the conversation, as the model is shown it."""

    role: Literal["user", "assistant"]
    text: str


class TurnRequest(DomainModel):
    """Everything a turn sends to the model, independent of the library that sends it."""

    model: str
    # Where and how to call the model.
    target: ModelTarget
    # The system prompt: what ADA is, the session, the rules and the message's context.
    instructions: str
    history: tuple[HistoryMessage, ...] = ()
    prompt: str
    # At most this many model requests; a turn that needs more fails.
    max_steps: int


class ToolSpec(DomainModel):
    """A tool the agent may call: one of the platform's MCP tools."""

    name: str
    description: str = ""
    input_schema: JsonObject = {}
