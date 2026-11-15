"""Reading cases sources (`access_kind: "cases"`): one table of a case type, read through
the case repository inside ADA, with no network, as Parquet in typed columns.

The columns follow ada.core.models.cases: the table's own, then for `cases` every field of
the case type as it is now (a day map one column per level), for `results` each section
column prefixed by the model kind, in the union over the rows. A column the source was
registered with and the data no longer has (a field removed while the type had no cases,
a model's column no result has yet) is kept, empty, so the declared schema always fits."""

import asyncio
import json
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from ada.core.models.analysis import FetchedData
from ada.core.models.base import Id
from ada.core.models.cases import (
    CASE_TABLE_COLUMNS,
    CaseTable,
    CaseType,
    case_table,
    case_type_address,
    field_cells,
    field_columns,
    result_column,
)
from ada.core.models.errors import Invalid, NotFound
from ada.core.models.schema import Column, ColumnType
from ada.core.models.sources import AccessKind, DataFormat, DataSource
from ada.core.models.time import TimeRange
from ada.core.ports.repositories import CaseRepository, StatisticalModelRepository
from ada.core.ports.sources import SourceReader, SourceReaders
from ada.core.ports.system import Clock

_DUCKDB_TYPES = {
    ColumnType.TEXT: "VARCHAR",
    ColumnType.INTEGER: "BIGINT",
    ColumnType.NUMBER: "DOUBLE",
    ColumnType.BOOLEAN: "BOOLEAN",
    ColumnType.DATE: "DATE",
    # In UTC, without a zone: reading a zoned timestamp back into Python needs pytz.
    ColumnType.TIMESTAMP: "TIMESTAMP",
    ColumnType.JSON: "JSON",
}

type Record = dict[str, Any]


class CaseSourceReader(SourceReader):
    """Reads a case type's cases, step events or results. The case type must belong to the
    source's project; the time range is not passed on: a cases source is read whole."""

    def __init__(
        self, cases: CaseRepository, models: StatisticalModelRepository, clock: Clock
    ) -> None:
        self.cases = cases
        self.models = models
        self.clock = clock

    async def fetch(self, source: DataSource, time_range: TimeRange) -> FetchedData:
        case_type = await self._case_type(source)
        table = case_table(source.options)
        match table:
            case CaseTable.CASES:
                columns, records = await self._cases(case_type)
            case CaseTable.EVENTS:
                columns, records = await self._events(case_type)
            case CaseTable.RESULTS:
                columns, records = await self._results(case_type)
        declared = source.declared_schema.columns if source.declared_schema else ()
        columns = _with_declared(columns, declared)
        content = await asyncio.to_thread(_parquet, columns, records)
        return FetchedData(
            content=content,
            format=DataFormat.PARQUET,
            fetched_at=self.clock.now(),
            origin=f"cases://{case_type.id}/{table.value}",
        )

    async def probe(self, source: DataSource) -> str | None:
        # Saving a case refreshes its sources (push); there is nothing cheaper to ask.
        return None

    async def _case_type(self, source: DataSource) -> CaseType:
        case_type = await self.cases.get_type(case_type_address(source.address))
        if case_type.project_id != source.project_id:
            raise Invalid(f"The case type {case_type.id} belongs to another project")
        return case_type

    async def _cases(self, case_type: CaseType) -> tuple[list[Column], list[Record]]:
        records = [
            {
                "key": case.key,
                "revision": case.revision,
                "created_at": case.created_at,
                "updated_at": case.updated_at,
                **field_cells(case_type.fields, case.values),
            }
            for case in await self.cases.list(case_type.id)
        ]
        columns = [*CASE_TABLE_COLUMNS[CaseTable.CASES], *field_columns(case_type.fields)]
        return columns, records

    async def _events(self, case_type: CaseType) -> tuple[list[Column], list[Record]]:
        records = [
            {
                "key": case.key,
                "field": event.field,
                "level": event.level,
                "old": None if event.old is None else json.dumps(event.old),
                "new": None if event.new is None else json.dumps(event.new),
                "recorded_at": event.recorded_at,
            }
            for case in await self.cases.list(case_type.id)
            for event in await self.cases.events(case.id)
        ]
        return list(CASE_TABLE_COLUMNS[CaseTable.EVENTS]), records

    async def _results(self, case_type: CaseType) -> tuple[list[Column], list[Record]]:
        names: dict[Id, str | None] = {}
        found: dict[str, ColumnType | None] = {}
        records: list[Record] = []
        for case in await self.cases.list(case_type.id):
            # Oldest first, as the other tables.
            for result in reversed(await self.cases.results(case.id)):
                if result.model_id not in names:
                    names[result.model_id] = await self._model_name(result.model_id)
                section = result.section
                record: Record = {
                    "key": case.key,
                    "model_id": str(result.model_id),
                    "model": names[result.model_id],
                    "version": result.version,
                    "case_revision": result.case_revision,
                    "trigger": result.trigger.value,
                    "created_at": result.created_at,
                    "summary": section.summary,
                    "open": section.attention.open,
                    "overdue_by": section.attention.overdue_by,
                    "due_in": section.attention.due_in,
                    "status": section.status,
                }
                for name, value in section.columns.items():
                    column = result_column(section.kind, name)
                    record[column] = value
                    found[column] = _widen(found.get(column), value)
                records.append(record)
        columns = [
            *CASE_TABLE_COLUMNS[CaseTable.RESULTS],
            *(Column(name=name, type=type or ColumnType.TEXT) for name, type in found.items()),
        ]
        return columns, records

    async def _model_name(self, model_id: Id) -> str | None:
        try:
            return (await self.models.get(model_id)).name
        except NotFound:
            return None


class CaseSourceReaders(SourceReaders):
    """The installed readers with the cases reader beside them. Built per unit of work,
    since the cases reader reads through that unit's repositories."""

    def __init__(self, readers: SourceReaders, cases: SourceReader) -> None:
        self.readers = readers
        self.cases = cases

    def for_kind(self, kind: AccessKind) -> SourceReader:
        if kind is AccessKind.CASES:
            return self.cases
        return self.readers.for_kind(kind)


def _widen(known: ColumnType | None, value: Any) -> ColumnType | None:
    """The type of a section column seen so far, given one more value: None until a value
    is not None, a number once integers and numbers mix, text when anything else does."""
    if value is None:
        return known
    if isinstance(value, bool):
        seen = ColumnType.BOOLEAN
    elif isinstance(value, int):
        seen = ColumnType.INTEGER
    elif isinstance(value, float):
        seen = ColumnType.NUMBER
    else:
        seen = ColumnType.TEXT
    if known is None or known is seen:
        return seen
    numeric = {ColumnType.INTEGER, ColumnType.NUMBER}
    return ColumnType.NUMBER if {known, seen} <= numeric else ColumnType.TEXT


def _with_declared(columns: list[Column], declared: Sequence[Column]) -> list[Column]:
    """The columns, a declared column's type in place of the one seen, and every declared
    column the data lacks at the end."""
    types = {column.name: column for column in declared}
    out = [types.get(column.name, column) for column in columns]
    present = {column.name for column in out}
    return out + [column for column in declared if column.name not in present]


def _parquet(columns: list[Column], records: list[Record]) -> bytes:
    """The records in the columns, each value converted to its column's type (one that
    does not convert is null)."""
    names = [_quote(column.name) for column in columns]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cases.parquet"
        with duckdb.connect(":memory:") as connection:
            raw = ", ".join(f"{name} VARCHAR" for name in names)
            connection.execute(f"CREATE TABLE records ({raw})")
            rows = [
                tuple(_text(record.get(column.name)) for column in columns) for record in records
            ]
            if rows:
                marks = ", ".join("?" for _ in columns)
                connection.executemany(f"INSERT INTO records VALUES ({marks})", rows)
            typed = ", ".join(
                f"TRY_CAST({name} AS {_DUCKDB_TYPES[column.type]}) AS {name}"
                for column, name in zip(columns, names, strict=True)
            )
            literal = "'" + str(path).replace("'", "''") + "'"
            connection.execute(f"COPY (SELECT {typed} FROM records) TO {literal} (FORMAT parquet)")
        return path.read_bytes()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None).isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
