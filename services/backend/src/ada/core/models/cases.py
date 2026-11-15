"""Case types, cases and the results models produce for them.

A case type is a schema of fields; a case is one instance of it under a key the caller
sets, so it can point at a record in another system. A statistical model names one case
type and runs on its cases: automatically on save when it is set to, on request
otherwise. Results are stored on the case as history and never overwritten. Synthetic
data only: the platform is not for patient data."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType


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
    """A field whose value changed at a save: the case's history. A day map changes per
    level, so `level` names the step and `old`/`new` are its days; for other fields
    `level` is None. `old` is None for a value set for the first time."""

    case_id: Id
    field: str
    level: str | None = None
    old: Any = None
    new: Any = None
    recorded_at: datetime


class ResultTrigger(StrEnum):
    AUTO = "auto"
    REQUEST = "request"


class Attention(DomainModel):
    """What a result says about whether the case needs someone: still open, how many
    days the most overdue thing is late, how many days until the next thing is due.
    Each model kind fills it from its own result; lists sort by it."""

    open: bool = False
    overdue_by: int | None = None
    due_in: int | None = None


class Section(DomainModel):
    """What one model said about one case. `body` is the model's own result (for
    `patient_pathway`, an Evaluation); `summary`, `status` and `columns` are what lists
    and the cases data source show."""

    kind: str
    title: str
    summary: str
    status: Literal["ok", "info", "warn", "urgent"] = "info"
    columns: dict[str, str | int | float | bool | None] = {}
    attention: Attention = Attention()
    body: JsonObject = {}
    # The data steps the model read for this result: its name for each -> the run it read.
    reads: dict[str, str] = {}


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
    # The fields of the case type this model reads; the others are the type's own.
    reads: tuple[str, ...] = ()
    latest: CaseResult | None
    results: int


class CaseWithResult(DomainModel):
    """A case with one model's latest result for it; None when the model has not run."""

    case: Case
    latest: CaseResult | None


class CaseWithResults(DomainModel):
    """A case with the latest result of each model on its type that has run on it."""

    case: Case
    latest: tuple[CaseResult, ...] = ()


class DefaultCaseType(DomainModel):
    """The case type a model kind brings: seeded when a model of the kind is created
    without one."""

    name: str
    description: str
    fields: tuple[Field, ...]


# The cases source (AccessKind.CASES): one table of a case type, read inside ADA. Its
# address is the case type's id, `options.table` the table. The column rules are here, so
# the registration, which declares the columns, and the reader, which fills them, agree.


class CaseTable(StrEnum):
    # One row per case: its key, revision and times, and every field of the case type.
    CASES = "cases"
    # One row per step event.
    EVENTS = "events"
    # One row per result, with its section's columns prefixed by the model kind.
    RESULTS = "results"


def case_table(options: JsonObject) -> CaseTable:
    """The table a cases source's options ask for; cases by default."""
    value = options.get("table", CaseTable.CASES.value)
    try:
        return CaseTable(value)
    except ValueError:
        tables = ", ".join(repr(table.value) for table in CaseTable)
        raise Invalid(f"options.table must be one of {tables}, not {value!r}") from None


def case_type_address(address: str) -> Id:
    """The case type a cases source's address names."""
    try:
        return UUID(address.strip())
    except ValueError:
        raise Invalid(
            f"The address of a cases source is a case type's id, not {address!r}"
        ) from None


def _required(name: str, type: ColumnType) -> Column:
    return Column(name=name, type=type, nullable=False)


# The columns every row of a table has, before the case type's fields (cases) or the
# models' columns (results).
CASE_TABLE_COLUMNS: dict[CaseTable, tuple[Column, ...]] = {
    CaseTable.CASES: (
        _required("key", ColumnType.TEXT),
        _required("revision", ColumnType.INTEGER),
        _required("created_at", ColumnType.TIMESTAMP),
        _required("updated_at", ColumnType.TIMESTAMP),
    ),
    CaseTable.EVENTS: (
        _required("key", ColumnType.TEXT),
        _required("field", ColumnType.TEXT),
        # The day map's level (a step); None for other fields.
        Column(name="level", type=ColumnType.TEXT),
        # The values as JSON text; None for the first value.
        Column(name="old", type=ColumnType.TEXT),
        Column(name="new", type=ColumnType.TEXT),
        _required("recorded_at", ColumnType.TIMESTAMP),
    ),
    CaseTable.RESULTS: (
        _required("key", ColumnType.TEXT),
        _required("model_id", ColumnType.TEXT),
        # None for a model that no longer exists.
        Column(name="model", type=ColumnType.TEXT),
        _required("version", ColumnType.INTEGER),
        _required("case_revision", ColumnType.INTEGER),
        _required("trigger", ColumnType.TEXT),
        _required("created_at", ColumnType.TIMESTAMP),
        _required("summary", ColumnType.TEXT),
        _required("status", ColumnType.TEXT),
        _required("open", ColumnType.BOOLEAN),
        Column(name="overdue_by", type=ColumnType.INTEGER),
        Column(name="due_in", type=ColumnType.INTEGER),
    ),
}

# The column each table's time role names, as its start and its end.
CASE_TIME_COLUMN: dict[CaseTable, str] = {
    CaseTable.CASES: "updated_at",
    CaseTable.EVENTS: "recorded_at",
    CaseTable.RESULTS: "created_at",
}

_FIELD_COLUMN_TYPES: dict[FieldType, ColumnType] = {
    FieldType.TEXT: ColumnType.TEXT,
    FieldType.NUMBER: ColumnType.NUMBER,
    FieldType.INTEGER: ColumnType.INTEGER,
    FieldType.DATE: ColumnType.DATE,
    FieldType.BOOLEAN: ColumnType.BOOLEAN,
    FieldType.ENUM: ColumnType.TEXT,
    # The values joined with commas.
    FieldType.ENUM_LIST: ColumnType.TEXT,
}


def field_columns(fields: tuple[Field, ...]) -> tuple[Column, ...]:
    """A nullable column per field; a day map is one integer column per level, named
    `<field>_<level>`."""
    columns: list[Column] = []
    for f in fields:
        if f.type is FieldType.DAY_MAP:
            columns.extend(
                Column(name=f"{f.name}_{level}", type=ColumnType.INTEGER) for level in f.levels
            )
        else:
            columns.append(Column(name=f.name, type=_FIELD_COLUMN_TYPES[f.type]))
    return tuple(columns)


def field_cells(fields: tuple[Field, ...], values: JsonObject) -> dict[str, Any]:
    """A case's values in the columns of `field_columns`; None where one is absent."""
    cells: dict[str, Any] = {}
    for f in fields:
        value = values.get(f.name)
        if f.type is FieldType.DAY_MAP:
            days = value if isinstance(value, dict) else {}
            cells.update({f"{f.name}_{level}": days.get(level) for level in f.levels})
        elif f.type is FieldType.ENUM_LIST:
            cells[f.name] = ",".join(value) if isinstance(value, list | tuple) else None
        else:
            cells[f.name] = value
    return cells


def result_column(kind: str, name: str) -> str:
    """The column of a section's column in the results table: prefixed by the model kind,
    e.g. patient_pathway_days_behind."""
    return f"{kind}_{name}"
