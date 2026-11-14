import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.schema import Schema

# An operator's id is its identity: the same kind, parameters and inputs are the same
# operator, whoever asks and however often.
type OperatorId = str


class OperatorKind(StrEnum):
    # Reads a registered data source. Parameters: SourceParams.
    SOURCE = "source"
    # Model-based extraction of rows from a document. Parameters: ExtractParams.
    EXTRACT = "extract"
    # A named, typed slot bound to another pipeline at run time. Parameters: InputParams.
    INPUT = "input"
    # SQL over earlier operators. Parameters: TransformParams.
    TRANSFORM = "transform"
    # A named statistical tool. Parameters: StatisticParams.
    STATISTIC = "statistic"
    # Generated text or judgement from incoming data and a prompt. Parameters: AgentParams.
    AGENT = "agent"


# Kinds whose output cannot be recomputed exactly, so their snapshot is evidence.
ALWAYS_MATERIALIZING = frozenset({OperatorKind.SOURCE, OperatorKind.EXTRACT, OperatorKind.AGENT})


class SourceParams(DomainModel):
    data_source_id: Id


class ExtractParams(DomainModel):
    # What to pull out of the document, in words.
    instruction: str
    model: str


class InputParams(DomainModel):
    # The slot's name; run bindings refer to it.
    name: str


class TransformParams(DomainModel):
    # Inputs are referred to as input_0, input_1, ... in the order of Operator.inputs.
    sql: str


class StatisticParams(DomainModel):
    tool: str
    arguments: JsonObject = {}
    # The query the statistic compiled to over input_0, kept so a run replays exactly
    # what was defined, even after the platform's statistics change.
    sql: str = ""


class AgentParams(DomainModel):
    prompt: str
    model: str


PARAMS: dict[OperatorKind, type[DomainModel]] = {
    OperatorKind.SOURCE: SourceParams,
    OperatorKind.EXTRACT: ExtractParams,
    OperatorKind.INPUT: InputParams,
    OperatorKind.TRANSFORM: TransformParams,
    OperatorKind.STATISTIC: StatisticParams,
    OperatorKind.AGENT: AgentParams,
}


class Operator(DomainModel):
    """One step of a pipeline. Immutable: changing anything makes a different operator.
    A pipeline is an operator together with everything upstream of it."""

    id: OperatorId
    project_id: Id
    kind: OperatorKind
    # Validates against PARAMS[kind]; kept as JSON so the identity is stable.
    params: JsonObject
    # Upstream operators, in the order the parameters refer to them.
    inputs: tuple[OperatorId, ...] = ()
    output: Schema
    # Stores a snapshot of its output instead of recomputing it. Always true for the
    # ALWAYS_MATERIALIZING kinds; elsewhere it is a cache the platform may choose.
    materializing: bool
    created_by: Actor
    created_at: datetime


def operator_identity(
    project_id: Id, kind: OperatorKind, params: JsonObject, inputs: Sequence[OperatorId]
) -> OperatorId:
    """The id of the operator with this definition. The declared output schema is not part
    of it: the same computation with a corrected declaration is still the same operator."""
    canonical = json.dumps(
        {"project": str(project_id), "kind": kind.value, "params": params, "inputs": list(inputs)},
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return "op_" + hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _json_default(value: Any) -> str:
    return str(value)
