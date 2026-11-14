"""Case types, cases and the results models produce for them.

A case type is a schema of fields; a case is one instance of it under a key the caller
sets, so it can point at a record in another system. A statistical model names one case
type and runs on its cases: automatically on save when it is set to, on request
otherwise. Results are stored on the case as history and never overwritten. Synthetic
data only: the platform is not for patient data."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    DATE = "date"
    BOOLEAN = "boolean"
    # One of `levels`.
    ENUM = "enum"
    # Any number of `levels`, no repeats.
    ENUM_LIST = "enum_list"
    # `levels` -> a non-negative whole number of days; a level left out has not started.
    DAY_MAP = "day_map"


class Field(DomainModel):
    name: str
    type: FieldType
    levels: tuple[str, ...] = ()
    required: bool = False
    label: str = ""
    help: str = ""


class Gap(DomainModel):
    """Why a case type does not cover what a model needs."""

    field: str
    problem: str


class CaseType(DomainModel):
    id: Id
    project_id: Id
    name: str
    description: str
    fields: tuple[Field, ...]
    # Counts schema changes; a case records the one it was last saved under.
    revision: int = 1
    created_by: Actor
    created_at: datetime


class Case(DomainModel):
    id: Id
    case_type_id: Id
    # Set by the caller, unique within the case type; never a personal identity code.
    key: str
    values: JsonObject
    schema_revision: int
    # Counts saves of the case.
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class CaseEvent(DomainModel):
    """A day-map field's step and its days, as recorded at a save: the history of a
    pathway as it grows."""

    case_id: Id
    field: str
    step: str
    days: int
    recorded_at: datetime


class ResultTrigger(StrEnum):
    AUTO = "auto"
    REQUEST = "request"


class Section(DomainModel):
    """What one model said about one case. `body` is the model's own result (for
    `patient_pathway`, an Evaluation); `summary`, `status` and `columns` are what lists
    and the cases data source show."""

    kind: str
    title: str
    summary: str
    status: Literal["ok", "info", "warn", "urgent"] = "info"
    columns: dict[str, str | int | float | bool | None] = {}
    body: JsonObject = {}


class CaseResult(DomainModel):
    id: Id
    case_id: Id
    model_id: Id
    version: int
    # The case revision the model read.
    case_revision: int
    section: Section
    trigger: ResultTrigger
    created_by: Actor
    created_at: datetime


class CaseState(DomainModel):
    """A case with its step events and every result, newest first."""

    case: Case
    events: tuple[CaseEvent, ...]
    results: tuple[CaseResult, ...]


class SavedCase(CaseState):
    # The models that ran automatically on this save.
    ran: tuple[Id, ...] = ()


class ModelOnCase(DomainModel):
    """A model on the case's type, with its latest result for the case if it has one."""

    model_id: Id
    name: str
    kind: str
    version: int
    auto_run: bool
    latest: CaseResult | None
    results: int


class CaseWithResult(DomainModel):
    """A case with one model's latest result for it; None when the model has not run."""

    case: Case
    latest: CaseResult | None
