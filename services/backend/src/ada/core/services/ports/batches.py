from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import ConfigDict, model_validator

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Roles, Schema
from ada.core.models.sources import AccessKind, DataFormat, FreshnessPolicy, Provenance
from ada.core.models.widgets import Widget

# In a step, a value "$name" stands for the result of the earlier step whose `ref` is
# "name"; any other value is the id of something that exists already.
REFERENCE = "$"

# The kinds of step, in the order of the fields of Step.
KINDS = ("register_source", "source_operator", "input", "transform", "widget")


class _Part(DomainModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RegisterSource(_Part):
    """As `register_source`. A source of the project with the same name and address is
    reused instead of registered twice. `refresh` queues a fetch once the batch is stored;
    the steps after it are checked against `declared_schema`, without data."""

    name: str
    address: str
    format: DataFormat = DataFormat.CSV
    access_kind: AccessKind = AccessKind.URL
    options: JsonObject | None = None
    freshness: FreshnessPolicy | None = None
    declared_schema: Schema | None = None
    provenance: Provenance | None = None
    refresh: bool = False


class SourceOperator(_Part):
    """As `add_source_operator`. A reference to a register step's source works too."""

    data_source_id: str


class InputSlot(_Part):
    """A named input with a declared schema, reading `default` unless a run binds it."""

    name: str
    output: Schema
    default: str


class Transform(_Part):
    """As `add_transform`: SQL over `inputs`, named input_0, input_1, ... in order."""

    sql: str
    inputs: tuple[str, ...] = ()
    roles: Roles | None = None
    materialize: bool = False


class WidgetPart(_Part):
    """As `create_widget`. The same widget asked for again (operator, type, title and
    spec, in the same session) is reused."""

    operator: str
    type: str
    title: str
    spec: JsonObject | None = None
    # Further inputs by name, each an operator id or "$ref" (see create_widget).
    inputs: dict[str, str] | None = None


class Step(_Part):
    """One step of a batch: exactly one of the kinds below, with an optional `ref` that
    later steps use as "$ref", and a `note` for the session, as the single tools take."""

    ref: str | None = None
    note: str = ""
    register_source: RegisterSource | None = None
    source_operator: SourceOperator | None = None
    input: InputSlot | None = None
    transform: Transform | None = None
    widget: WidgetPart | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        kinds = [k for k in KINDS if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError(f"A step has exactly one of {', '.join(KINDS)}; this has {kinds}")
        return self

    @property
    def kind(self) -> str:
        return next(k for k in KINDS if getattr(self, k) is not None)


class Batch(DomainModel):
    """What a batch made, or found already made."""

    # Each step's ref: a source id, an operator id or a widget id.
    refs: dict[str, str]
    # The widgets of the batch, in step order.
    widgets: tuple[Widget, ...] = ()


class BatchService(Protocol):
    async def build(
        self, project_id: Id, steps: Sequence[Step], actor: Actor, session_id: Id | None = None
    ) -> Batch:
        """Carry out the steps in order through the same services the single tools use,
        so each is checked as it would be alone. With `session_id` every step but a
        registration gets its session entry, unless the session already shows that
        operator or widget.

        It runs in the caller's unit of work, so it is stored whole or not at all: the
        first step that fails raises, naming its index and ref. Running the same steps
        again finds what they made (operators by identity, sources by name and address,
        widgets by definition) and makes nothing new."""
        ...
