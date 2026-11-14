"""The text widget: Markdown whose figures come from the widget's inputs, by placeholder.

    {{gap.value}}                 the column `value` of the input `gap`
    {{gap.value:percent}}         the same value in a number format (FORMATS)
    {{gap.value[county=Kainuu]}}  in the row where `county` is `Kainuu`; filters chain
    {{gap}}                       the whole input, as a compact table
    \\{{                           two literal braces

A value is the latest period's when the input has a time role, else the input's only row:
exactly one row must remain, or the placeholder has no value (the reason says why). The
check at creation (`text_problems`) needs no data; values are resolved for the judge
(`resolve`) and drawn by the widget bundle, which follows the same rules.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ada.core.models.base import JsonObject
from ada.core.models.schema import Column, ColumnType, OutputKind, Schema

TEXT_TYPE = "text"
MARKDOWN_KEY = "markdown"
MAX_MARKDOWN = 20_000
# The most rows `{{input}}` shows; the widget says when there are more.
MAX_TABLE_ROWS = 50

FORMATS = ("integer", "number1", "percent", "plain", "signed1")
_NUMBER_FORMATS = frozenset({"integer", "number1", "percent", "signed1"})
_NUMERIC = frozenset({ColumnType.INTEGER, ColumnType.NUMBER})

_NAME = r"[a-z][a-z0-9_]{0,31}"
_COLUMN = r"[A-Za-z_][A-Za-z0-9_]*"
_PLACEHOLDER = re.compile(
    rf"""\{{\{{\s*
    (?P<input>{_NAME})
    (?:\.(?P<column>{_COLUMN})
       (?P<filters>(?:\[{_COLUMN}=[^\]\n{{}}]+\])*)
       (?::(?P<format>[a-z0-9]+))?
    )?
    \s*\}}\}}""",
    re.VERBOSE,
)
_FILTER = re.compile(rf"\[({_COLUMN})=([^\]]+)\]")
# Raw HTML is refused; a CommonMark autolink (<https://...>) is a link, not HTML.
_HTML = re.compile(r"<\s*/?\s*(?!https?://|mailto:)[A-Za-z!][^>\n]*>")
_IMAGE = re.compile(r"!\[[^\]\n]*\]\s*[\(\[]")
_YEAR = re.compile(r"(.*_)?year")
# The minus sign the widget writes, not a hyphen.
MINUS = "\u2212"


@dataclass(frozen=True)
class Placeholder:
    # As written, e.g. "{{gap.value:percent}}".
    text: str
    input: str
    # None for the whole input.
    column: str | None = None
    filters: tuple[tuple[str, str], ...] = ()
    format: str | None = None
    line: int = 1

    @property
    def name(self) -> str:
        """How the judge sees it: input.column[filters]."""
        if self.column is None:
            return self.input
        filters = "".join(f"[{column}={value}]" for column, value in self.filters)
        return f"{self.input}.{self.column}{filters}"


type Segment = str | Placeholder


def parse(markdown: str) -> tuple[list[Segment], list[str]]:
    """The Markdown as literal text and placeholders, and what is malformed: a `{{` that
    starts no placeholder (write `\\{{` for literal braces)."""
    segments: list[Segment] = []
    problems: list[str] = []
    literal: list[str] = []
    position = 0
    while position < len(markdown):
        if markdown.startswith("\\{{", position):
            literal.append("{{")
            position += 3
            continue
        if markdown.startswith("{{", position):
            match = _PLACEHOLDER.match(markdown, position)
            line = markdown.count("\n", 0, position) + 1
            if match is None:
                shown = markdown[position : position + 40].split("\n")[0]
                problems.append(
                    f"line {line}: `{shown}` is not a placeholder; write {{{{input.column}}}}, "
                    "{{input.column:format}}, {{input.column[column=value]}} or {{input}}, "
                    "and \\{{ for literal braces"
                )
                literal.append("{{")
                position += 2
                continue
            if literal:
                segments.append("".join(literal))
                literal = []
            segments.append(
                Placeholder(
                    text=match.group(0),
                    input=match.group("input"),
                    column=match.group("column"),
                    filters=tuple(
                        (column, value.strip())
                        for column, value in _FILTER.findall(match.group("filters") or "")
                    ),
                    format=match.group("format"),
                    line=line,
                )
            )
            position = match.end()
            continue
        literal.append(markdown[position])
        position += 1
    if literal:
        segments.append("".join(literal))
    return segments, problems


def placeholders(markdown: str) -> list[Placeholder]:
    return [segment for segment in parse(markdown)[0] if isinstance(segment, Placeholder)]


def text_problems(spec: JsonObject, inputs: Mapping[str, Schema]) -> tuple[list[str], list[str]]:
    """What is wrong with a text widget's spec against its inputs' output schemas (every
    problem, for one Invalid), and what is likely unintended (warnings: an input that no
    placeholder reads). Columns not known yet (a source without a declared schema) are
    not checked."""
    unknown = sorted(set(spec) - {MARKDOWN_KEY})
    if unknown:
        return [f"a text widget's spec holds only `markdown`, not {unknown}"], []
    markdown = spec.get(MARKDOWN_KEY)
    if not isinstance(markdown, str) or not markdown.strip():
        return ["a text widget needs `markdown`: the text, with figures as placeholders"], []
    problems: list[str] = []
    if len(markdown) > MAX_MARKDOWN:
        problems.append(f"`markdown` has {len(markdown):,} characters; at most {MAX_MARKDOWN:,}")
    if match := _HTML.search(markdown):
        problems.append(f"raw HTML is not allowed (`{match.group(0)[:40]}`); write Markdown")
    if _IMAGE.search(markdown):
        problems.append("images are not allowed in a text widget; show data in a widget")
    segments, malformed = parse(markdown)
    problems += malformed
    used: set[str] = set()
    for placeholder in (s for s in segments if isinstance(s, Placeholder)):
        used.add(placeholder.input)
        problems += _placeholder_problems(placeholder, inputs)
    warnings = [
        f"the input {name!r} is not used by any placeholder" for name in inputs if name not in used
    ]
    return problems, warnings


def _placeholder_problems(placeholder: Placeholder, inputs: Mapping[str, Schema]) -> list[str]:
    where = f"`{placeholder.text}` (line {placeholder.line})"
    schema = inputs.get(placeholder.input)
    if schema is None:
        return [
            f"{where}: there is no input {placeholder.input!r}; the widget has {_names(inputs)}"
        ]
    if schema.kind is not OutputKind.TABLE:
        return [f"{where}: the input {placeholder.input!r} is a {schema.kind.value}, not a table"]
    problems: list[str] = []
    columns = {column.name: column for column in schema.columns}
    if placeholder.format is not None and placeholder.format not in FORMATS:
        problems.append(f"{where}: the format must be {_formats()}, not {placeholder.format!r}")
    if not columns:
        return problems
    if placeholder.column is not None:
        column = columns.get(placeholder.column)
        if column is None:
            problems.append(
                f"{where}: the input {placeholder.input!r} has no column {placeholder.column!r}"
            )
        elif placeholder.format in _NUMBER_FORMATS and column.type not in _NUMERIC:
            problems.append(
                f"{where}: the format {placeholder.format!r} needs a number, and "
                f"{placeholder.column!r} is {column.type}"
            )
    problems += [
        f"{where}: the input {placeholder.input!r} has no column {name!r} to filter on"
        for name, _ in placeholder.filters
        if name not in columns
    ]
    return problems


# Resolving: what a placeholder shows in a run


@dataclass(frozen=True)
class InputRows:
    """One input as a run reads it."""

    output: Schema
    columns: tuple[Column, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool = False


class NoValue(Exception):
    """A placeholder has no value in this run; the message says why."""


def value(placeholder: Placeholder, data: InputRows) -> tuple[Any, Column]:
    """The cell a placeholder shows, and its column. Raises NoValue."""
    if placeholder.column is None:
        raise NoValue("a whole input is a table, not a value")
    index = _index(data.columns)
    if placeholder.column not in index:
        raise NoValue(f"the input has no column {placeholder.column!r}")
    if data.truncated:
        raise NoValue(f"the input has more than the {len(data.rows)} rows a widget reads")
    rows = list(data.rows)
    for name, wanted in placeholder.filters:
        if name not in index:
            raise NoValue(f"the input has no column {name!r}")
        rows = [
            row
            for row in rows
            if row[index[name]] is not None and _text(row[index[name]]) == wanted
        ]
    time = data.output.roles.time
    if time is not None and rows:
        period = time.end if time.end in index else time.start
        if period in index:
            latest = max(
                (_text(row[index[period]]) for row in rows if row[index[period]] is not None),
                default=None,
            )
            rows = [row for row in rows if _text(row[index[period]]) == latest]
    if not rows:
        raise NoValue("no row matches" if placeholder.filters else "the input has no rows")
    if len(rows) > 1:
        what = "in the latest period" if time is not None else "and no time role"
        raise NoValue(f"{len(rows)} rows remain {what}; pick one with [column=value]")
    measure = next((m for m in data.output.roles.measures if m.value == placeholder.column), None)
    if measure is not None and measure.suppressed in index and rows[0][index[measure.suppressed]]:
        raise NoValue("the value was withheld, e.g. for a small count")
    cell = rows[0][index[placeholder.column]]
    if cell is None:
        raise NoValue("the value is empty")
    column = data.columns[index[placeholder.column]]
    return cell, column


def formatted(cell: Any, column: Column, format: str | None, output: Schema) -> str:
    """The value as the widget bundle writes it (services/widgets: `text/model.ts` and
    `lib/columns.ts`), so the judge reads what readers see. Without a format: years and
    the time role's columns plain, other numbers with thousands separators and at most two
    decimals below 100, none from 100. `percent` has at most one decimal, `number1`
    exactly one, and `signed1` says which way it goes ("+1.3", "−1.3", "±0.0")."""
    if format == "plain" or (format is None and _plain(column, output)):
        return _text(cell)
    if isinstance(cell, bool) or not isinstance(cell, int | float):
        if format is None and isinstance(cell, bool):
            return "yes" if cell else "no"
        return _text(cell)
    match format:
        case None:
            return _number(cell, 0 if abs(cell) >= 100 else 2)
        case "integer":
            return _number(cell, 0)
        case "number1":
            return _number(cell, 1, 1)
        case "percent":
            return f"{_number(cell, 1)} %"
        case "signed1":
            text = _number(abs(cell), 1, 1)
            if text == _number(0, 1, 1):
                return f"±{text}"
            return f"{'+' if cell > 0 else MINUS}{text}"
        case _:
            return _text(cell)


def resolve(segments: Sequence[Segment], data: Mapping[str, InputRows]) -> str:
    """The Markdown with each placeholder resolved and tagged, as the judge reads it:
    `⟦gap.value = 13.2⟧`, `⟦gap.value: no value, <why>⟧`, `⟦gap: the table of the input⟧`."""
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, str):
            parts.append(segment)
            continue
        rows = data.get(segment.input)
        if rows is None:
            parts.append(f"⟦{segment.name}: no value, there is no such input⟧")
        elif segment.column is None:
            shown = min(len(rows.rows), MAX_TABLE_ROWS)
            parts.append(f"⟦{segment.name}: the input's table, {shown} rows⟧")
        else:
            try:
                cell, column = value(segment, rows)
            except NoValue as reason:
                parts.append(f"⟦{segment.name}: no value, {reason}⟧")
            else:
                shown_value = formatted(cell, column, segment.format, rows.output)
                parts.append(f"⟦{segment.name} = {shown_value}⟧")
    return "".join(parts)


def _plain(column: Column, output: Schema) -> bool:
    """Integer years (`year`, `*_year`) and the time role's columns are labels, not
    amounts: written as they are."""
    time = output.roles.time
    year = column.type is ColumnType.INTEGER and bool(_YEAR.fullmatch(column.name.lower()))
    return year or (time is not None and column.name in (time.start, time.end))


def _number(number: float, most: int, least: int = 0) -> str:
    """With thousands separators, rounded half away from zero (as Intl.NumberFormat does)
    to at most `most` decimals, keeping at least `least`."""
    rounded = Decimal(str(number)).quantize(Decimal(1).scaleb(-most), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    text = f"{rounded:,f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0").ljust(least, "0")
    return f"{whole}.{fraction}" if fraction else whole


def _text(cell: Any) -> str:
    """A cell as JavaScript's String() writes it, which is what the widget compares."""
    if isinstance(cell, bool):
        return "true" if cell else "false"
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    if hasattr(cell, "isoformat"):
        return cell.isoformat()
    return str(cell)


def _index(columns: Sequence[Column]) -> dict[str, int]:
    return {column.name: position for position, column in enumerate(columns)}


def _names(inputs: Mapping[str, Schema]) -> str:
    return ", ".join(inputs) or "none"


def _formats() -> str:
    return ", ".join(f'"{name}"' for name in FORMATS[:-1]) + f' or "{FORMATS[-1]}"'
