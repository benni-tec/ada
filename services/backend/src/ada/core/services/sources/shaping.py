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
    or {column: {"path": path, "type": "integer" | "number" | "text" | "boolean"}} to also
    convert the value, e.g. a number sent as a string. Without it every record is
    flattened: nested objects become columns joined with "_", e.g. survival_value.
`csv` (CSV)
    {"delimiter": ",", "encoding": "utf-8", "skip_rows": 0, "columns": [...],
    "null_values": [...]}, all optional. `skip_rows` drops lines before the header,
    `columns` replaces the header's names, and cells equal to one of `null_values` (e.g.
    ".." in PxWeb tables) become empty. The output is UTF-8 with commas. Without `csv` the
    bytes are kept as they came.

JSON output is always an array of flat records that all have the same keys in the same
order, missing ones as null.
"""

import csv
import io
import json
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from ada.core.models.analysis import FetchedData
from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.sources import DataFormat

type FieldType = Literal["integer", "number", "text", "boolean"]


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


class ShapeOptions(DomainModel):
    rows: str | None = None
    fields: dict[str, str | FieldOption] | None = None
    csv: CsvOptions | None = None


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
        case DataFormat.CSV if parsed.csv is not None:
            content = _shape_csv(data.content, parsed.csv)
        case _:
            return data
    return data.model_copy(update={"content": content})


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
    # One key order for every record, so the columns do not depend on which row came first.
    columns = list(dict.fromkeys(key for record in records for key in record))
    table = [{column: record.get(column) for column in columns} for record in records]
    return json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode()


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


def _shape_csv(content: bytes, options: CsvOptions) -> bytes:
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
    nulls = set(options.null_values)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for number, row in enumerate(body, start=2 + options.skip_rows):
        if len(row) != len(header):
            raise Invalid(f"CSV record {number} has {len(row)} cells, the header {len(header)}")
        writer.writerow("" if cell in nulls else cell for cell in row)
    return out.getvalue().encode()
