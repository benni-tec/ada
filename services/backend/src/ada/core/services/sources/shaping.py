"""Turning what a source answered into a table the analysis store can read.

APIs rarely answer with a plain table: the rows sit somewhere inside a JSON document,
records nest objects, numbers come as strings, and CSV exports carry a byte order mark,
semicolons or "..". Shaping happens before the store sees the bytes, so every snapshot of
a source has the same plain form, and the content hash compares like with like.

These keys of `DataSource.options` control it; the readers ignore them.

`rows` (JSON)
    Dot path to the array of records, e.g. "dataset" or "data.items". A segment of digits
    indexes an array. Without it the whole document is the array; a single object is one
    record.
`fields` (JSON)
    The columns to keep, as {column: path} where the path is a dot path inside a record,
    or {column: {"path": path, "type": "integer" | "number" | "text" | "boolean" |
    "json"}} to also convert the value, e.g. a number sent as a string. "json" keeps a
    nested value, such as a GeoJSON geometry, as its JSON text in one column. Without
    `fields` every record is flattened: nested objects become columns joined with "_",
    e.g. survival_value.
`csv` (CSV)
    {"delimiter": ",", "encoding": "utf-8", "skip_rows": 0, "columns": [...],
    "null_values": [...]}, all optional. `skip_rows` drops lines before the header,
    `columns` replaces the header's names, and cells equal to one of `null_values` (e.g.
    ".." in PxWeb tables) become empty. The output is UTF-8 with commas. Without `csv` (and
    without `period`) the bytes are kept as they came.
`period` (JSON and CSV)
    {"column": "year", "start": "period_start", "end": "period_end", "grain": "year"}:
    adds the period each row describes as two date columns, the first and the last day,
    read from the source's own way of writing it in `column`: a year (2024 or "2024"), a
    window ("2020-2024"), a quarter ("2024Q1"), a month ("2024M03") or a date, which
    `grain` widens to the year, quarter or month around it
    (ada.core.services.schema.time.parse_period). `start` and `end` default to
    period_start and period_end; declare them as the time role. Applied after `fields`.

JSON output is always an array of flat records that all have the same keys in the same
order, missing ones as null.
"""

import csv
import io
import json
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, model_validator

from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import TimeRole
from ada.core.models.sources import DataFormat
from ada.core.models.time import Grain, Interval
from ada.core.services.schema.time import parse_period

type FieldType = Literal["integer", "number", "text", "boolean", "json"]


class FieldOption(DomainModel):
    path: str = Field(min_length=1)
    type: FieldType | None = None


class CsvOptions(DomainModel):
    delimiter: Annotated[str, Field(min_length=1, max_length=1)] = ","
    # A UTF-8 byte order mark is dropped whatever this says: PxWeb sends one while its
    # header claims Windows-1252.
    encoding: str = "utf-8"
    skip_rows: int = Field(default=0, ge=0)
    columns: tuple[str, ...] | None = None
    null_values: tuple[str, ...] = ()


class PeriodOption(DomainModel):
    column: str = Field(min_length=1)
    start: str = Field(default="period_start", min_length=1)
    end: str = Field(default="period_end", min_length=1)
    grain: Grain | None = None

    @model_validator(mode="after")
    def _distinct(self) -> PeriodOption:
        if self.start == self.end:
            raise ValueError("the period's start and end need two different columns")
        return self


class ShapeOptions(DomainModel):
    include_provenance: bool = False
    rows: str | None = None
    fields: dict[str, str | FieldOption] | None = None
    csv: CsvOptions | None = None
    period: PeriodOption | None = None


def shape_options(options: JsonObject) -> ShapeOptions:
    """The shaping keys of a source's options. Raises Invalid when one is malformed, so a
    registration fails at once rather than at its first refresh."""
    keys = ShapeOptions.model_fields.keys()
    try:
        return ShapeOptions.model_validate({k: v for k, v in options.items() if k in keys})
    except ValidationError as error:
        raise Invalid(f"Invalid source options: {error}") from None


def shape(data: FetchedData, options: JsonObject) -> FetchedData:
    """The fetched data as a plain table of the same format. Raises Invalid when the
    content does not have the shape the options describe."""
    parsed = shape_options(options)
    match data.format:
        case DataFormat.JSON:
            content = _shape_json(data.content, parsed)
            if parsed.include_provenance:
                provenance = {"source_url": data.origin, "fetched_at": data.fetched_at.isoformat()}
                content = _json(
                    [
                        {
                            key: value
                            for key, value in record.items()
                            if key.casefold() not in provenance
                        }
                        | provenance
                        for record in json.loads(content)
                    ]
                )
        case DataFormat.CSV if (
            parsed.csv is not None or parsed.period is not None or parsed.include_provenance
        ):
            content = _shape_csv(data.content, parsed.csv or CsvOptions(), parsed.period)
            if parsed.include_provenance:
                rows = list(csv.reader(io.StringIO(content.decode())))
                if rows:
                    if {"source_url", "fetched_at"} & {name.casefold() for name in rows[0]}:
                        raise Invalid(
                            "CSV provenance columns source_url and fetched_at are reserved"
                        )
                    rows = [
                        rows[0] + ["source_url", "fetched_at"],
                        *[row + [data.origin, data.fetched_at.isoformat()] for row in rows[1:]],
                    ]
                    content = _csv(rows)
        case _:
            return data
    return data.model_copy(update={"content": content})


def split_periods(
    data: FetchedData, time: TimeRole, wanted: Sequence[Interval]
) -> dict[Interval, FetchedData]:
    """Shaped data cut into one table per period, by the time role's columns: what a
    source answered for several periods at once, stored one snapshot per period. Periods
    without rows are left out. Raises Invalid for a row of a period that was not asked
    for, or without a period: such a source cannot fetch by period."""
    wanted_set = set(wanted)
    match data.format:
        case DataFormat.JSON:
            records = json.loads(data.content)
            parts: dict[Interval, list[Any]] = {}
            for record in records:
                period = _row_period(record.get(time.start), record.get(time.end), wanted_set)
                parts.setdefault(period, []).append(record)
            return {
                period: data.model_copy(update={"content": _json(rows)})
                for period, rows in parts.items()
            }
        case DataFormat.CSV:
            header, *body = list(csv.reader(io.StringIO(data.content.decode())))
            if time.start not in header or time.end not in header:
                raise Invalid(f"The data has no columns {time.start!r} and {time.end!r}")
            start, end = header.index(time.start), header.index(time.end)
            groups: dict[Interval, list[list[str]]] = {}
            for row in body:
                period = _row_period(row[start], row[end], wanted_set)
                groups.setdefault(period, []).append(row)
            return {
                period: data.model_copy(update={"content": _csv([header, *rows])})
                for period, rows in groups.items()
            }
        case _:
            raise Invalid(f"Splitting {data.format.value} data by period is not supported")


def _row_period(start: Any, end: Any, wanted: set[Interval]) -> Interval:
    try:
        period = Interval(start=_day(start), end=_day(end))
    except TypeError, ValueError:
        raise Invalid(f"A row has no period: {start!r} to {end!r}") from None
    if period not in wanted:
        raise Invalid(
            f"The source answered for {period.start} to {period.end}, which was not asked "
            "for; a source that fetches by period must answer per requested period"
        )
    return period


def _day(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _shape_json(content: bytes, options: ShapeOptions) -> bytes:
    try:
        document = json.loads(content)
    except ValueError as error:
        raise Invalid(f"The source did not answer with JSON: {error}") from None
    found = _at(document, options.rows) if options.rows else document
    if isinstance(found, dict):
        found = [found]
    if not isinstance(found, list) or not all(isinstance(row, dict) for row in found):
        where = f" at {options.rows!r}" if options.rows else ""
        raise Invalid(f"Expected an array of records{where}")
    if options.fields is not None:
        records = [_pick(row, options.fields) for row in found]
    else:
        records = [_flatten(row) for row in found]
    if options.period is not None:
        records = [_with_period(record, options.period) for record in records]
    # One key order for every record, so the columns do not depend on which row came first.
    columns = list(dict.fromkeys(key for record in records for key in record))
    table = [{column: record.get(column) for column in columns} for record in records]
    return _json(table)


def _json(table: list[Any]) -> bytes:
    return json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode()


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode()


def _with_period(record: dict[str, Any], option: PeriodOption) -> dict[str, Any]:
    start, end = _period(record.get(option.column), option)
    return record | {option.start: start, option.end: end}


def _period(value: Any, option: PeriodOption) -> tuple[str | None, str | None]:
    """The period's first and last day as ISO dates, which DuckDB reads as dates."""
    try:
        period = parse_period(value, option.grain)
    except ValueError as error:
        raise Invalid(f"Column {option.column}: {error}") from None
    if period is None:
        return None, None
    return period.start.isoformat(), period.end.isoformat()


def _at(document: Any, path: str) -> Any:
    found = document
    for segment in path.split("."):
        if isinstance(found, dict) and segment in found:
            found = found[segment]
        elif isinstance(found, list) and segment.isdigit() and int(segment) < len(found):
            found = found[int(segment)]
        else:
            raise Invalid(f"Nothing at {path!r} in the source's answer")
    return found


def _flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}_"))
        else:
            flat[name] = value
    return flat


def _pick(record: dict[str, Any], fields: dict[str, str | FieldOption]) -> dict[str, Any]:
    picked: dict[str, Any] = {}
    for column, spec in fields.items():
        field = spec if isinstance(spec, FieldOption) else FieldOption(path=spec)
        value = _get(record, field.path)
        picked[column] = _convert(value, field.type, column) if field.type else value
    return picked


def _get(record: dict[str, Any], path: str) -> Any:
    # A missing field is a null, not an error: APIs leave out empty values.
    found: Any = record
    for segment in path.split("."):
        if not isinstance(found, dict):
            return None
        found = found.get(segment)
    return found


def _convert(value: Any, kind: FieldType, column: str) -> Any:
    if value is None or value == "":
        return None
    try:
        match kind:
            case "integer":
                number = float(value)
                if not number.is_integer():
                    raise ValueError(f"{value!r} is not a whole number")
                return int(number)
            case "number":
                return float(value)
            case "text":
                return str(value)
            case "json":
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            case "boolean":
                if isinstance(value, bool):
                    return value
                if str(value).lower() in {"true", "1", "yes"}:
                    return True
                if str(value).lower() in {"false", "0", "no"}:
                    return False
                raise ValueError(f"{value!r} is not a boolean")
    except (TypeError, ValueError) as error:
        raise Invalid(f"Column {column}: cannot read {value!r} as {kind}: {error}") from None


def _shape_csv(content: bytes, options: CsvOptions, period: PeriodOption | None) -> bytes:
    try:
        text = content.removeprefix(b"\xef\xbb\xbf").decode(options.encoding)
    except (LookupError, UnicodeDecodeError) as error:
        raise Invalid(f"Cannot decode the CSV as {options.encoding}: {error}") from None
    lines = text.splitlines(keepends=True)[options.skip_rows :]
    rows = [row for row in csv.reader(lines, delimiter=options.delimiter) if row]
    if not rows:
        raise Invalid("The CSV has no header row")
    header, *body = rows
    if options.columns is not None:
        if len(options.columns) != len(header):
            raise Invalid(
                f"The csv option names {len(options.columns)} columns, "
                f"but the CSV has {len(header)}: {header}"
            )
        header = list(options.columns)
    if period is not None and period.column not in header:
        raise Invalid(f"The period option names {period.column!r}, which is not a column")
    nulls = set(options.null_values)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header + ([period.start, period.end] if period else []))
    for number, row in enumerate(body, start=2 + options.skip_rows):
        if len(row) != len(header):
            raise Invalid(f"CSV record {number} has {len(row)} cells, the header {len(header)}")
        cells = ["" if cell in nulls else cell for cell in row]
        if period is not None:
            start, end = _period(cells[header.index(period.column)], period)
            cells += [start or "", end or ""]
        writer.writerow(cells)
    return out.getvalue().encode()
