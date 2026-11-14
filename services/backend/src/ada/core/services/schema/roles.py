"""Checking role declarations: against the columns they name, a binding against the slot it
fills, and a widget against the roles and columns it needs. Everything here runs before
any data is fetched (spec: Operators declare their output schema)."""

from collections.abc import Iterable

from ada.core.models.base import JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, MeasureRole, OutputKind, Roles, Schema
from ada.core.services.schema.geo import MIXED
from ada.core.services.widgets.specs import chart_problems, table_problems, value_problems

NUMERIC = frozenset({ColumnType.INTEGER, ColumnType.NUMBER})
TIME = frozenset({ColumnType.DATE, ColumnType.TIMESTAMP})
# A geometry is GeoJSON, as an object or as its text.
GEOMETRY = frozenset({ColumnType.JSON, ColumnType.TEXT})


def check_roles(roles: Roles, columns: tuple[Column, ...]) -> None:
    """Roles must name columns that exist and whose types fit what the role means: a
    period's ends are dates, a measure and its bounds are numbers, a suppression flag is
    a boolean."""
    by_name = {column.name: column for column in columns}
    problems: list[str] = []

    def need(name: str, role: str, types: Iterable[ColumnType] | None = None) -> None:
        column = by_name.get(name)
        if column is None:
            problems.append(f"{role} names {name!r}, which is not a column")
        elif types is not None and column.type not in types:
            problems.append(f"{role} needs {name!r} to be {_one_of(types)}, not {column.type}")

    if roles.time:
        need(roles.time.start, "the time start", TIME)
        need(roles.time.end, "the time end", TIME)
    if roles.geo:
        need(roles.geo.code, "the region code")
        if not roles.geo.system.strip() or not roles.geo.level.strip():
            problems.append("the region code needs a code system and a level")
    for measure in roles.measures:
        need(measure.value, "a measure", NUMERIC)
        for name, role in (
            (measure.lower, "a lower bound"),
            (measure.upper, "an upper bound"),
            (measure.coverage, "a coverage"),
        ):
            if name is not None:
                need(name, role, NUMERIC)
        if (measure.lower is None) != (measure.upper is None):
            problems.append(f"the measure {measure.value!r} needs both bounds or neither")
        if measure.suppressed is not None:
            need(measure.suppressed, "a suppression flag", {ColumnType.BOOLEAN})
    if problems:
        raise Invalid("The roles do not fit the columns: " + "; ".join(problems))


def check_compatible(slot: Roles, bound: Roles, what: str) -> None:
    """Whether a pipeline with roles `bound` can fill a slot declared with roles `slot`:
    the same period shape and the same geography, not only the same column names. A
    binding with annual rows by county must not fill a slot for quarters by
    municipality, even though both have a period, a region and a value."""
    problems: list[str] = []
    if slot.time:
        if bound.time is None:
            problems.append("it declares no time role, and the slot has periods")
        else:
            if (bound.time.start, bound.time.end) != (slot.time.start, slot.time.end):
                problems.append(
                    f"its periods are in {bound.time.start!r}/{bound.time.end!r}, "
                    f"the slot's in {slot.time.start!r}/{slot.time.end!r}"
                )
            if slot.time.grain is not None and bound.time.grain != slot.time.grain:
                problems.append(
                    f"its periods are {_grain(bound.time.grain)}, "
                    f"the slot's {_grain(slot.time.grain)}"
                )
    if slot.geo:
        if bound.geo is None:
            problems.append("it declares no geography role, and the slot has regions")
        else:
            if bound.geo.code != slot.geo.code:
                problems.append(
                    f"its region code is {bound.geo.code!r}, the slot's {slot.geo.code!r}"
                )
            if (bound.geo.system, bound.geo.level) != (slot.geo.system, slot.geo.level):
                problems.append(
                    f"its regions are {bound.geo.level} in {bound.geo.system} codes, "
                    f"the slot's {slot.geo.level} in {slot.geo.system} codes"
                )
    if problems:
        raise Invalid(f"{what} does not have the slot's roles: " + "; ".join(problems))


def check_widget(type: str, output: Schema, spec: JsonObject) -> None:
    """Whether a widget of this type can show the output: the roles and columns it needs
    are declared, and what its spec names exists. Columns that are not known yet (a
    source registered without a schema) are not checked; roles always are. Types the
    platform does not know are not checked."""
    if type not in _NEEDS:
        return
    if output.kind is not OutputKind.TABLE:
        raise Invalid(f"A {type} widget shows a table; operator output is a {output.kind.value}")
    problems = _NEEDS[type](output, spec, {column.name: column for column in output.columns})
    if problems:
        raise Invalid(f"A {type} widget cannot show this output: " + "; ".join(problems))


type _Columns = dict[str, Column]


def _value(output: Schema, spec: JsonObject, columns: _Columns) -> list[str]:
    return _measure(output, spec, columns, "column") + value_problems(spec, columns)


def _table(output: Schema, spec: JsonObject, columns: _Columns) -> list[str]:
    options = table_problems(spec, columns)
    wanted = spec.get("columns")
    if wanted is None or not columns:
        return options
    if not isinstance(wanted, list) or not all(isinstance(name, str) for name in wanted):
        return ["`columns` must be a list of column names", *options]
    return [f"there is no column {name!r}" for name in wanted if name not in columns] + options


def _chart(output: Schema, spec: JsonObject, columns: _Columns) -> list[str]:
    return chart_problems(spec)


def _line_chart(output: Schema, spec: JsonObject, columns: _Columns) -> list[str]:
    problems = _spec_columns(spec, columns, "x", "series")
    x = _text(spec, "x") or (output.roles.time.start if output.roles.time else None)
    if x is None and columns:
        x = next((c.name for c in columns.values() if c.type in TIME), next(iter(columns)))
    return problems + _measure(output, spec, columns, "y", exclude=x)


def _map(output: Schema, spec: JsonObject, columns: _Columns) -> list[str]:
    problems: list[str] = []
    geo = output.roles.geo
    if geo is None:
        problems.append(
            "it needs a geography role: declare which column holds the region code, "
            "its code system and its level"
        )
    elif geo.level == MIXED:
        problems.append(
            f"its regions are of mixed levels; filter {geo.code!r} to one level and "
            "declare that level"
        )
    geometry = _text(spec, "geometry") or "geometry"
    if columns:
        column = columns.get(geometry)
        if column is None:
            problems.append(
                f"it needs the region boundaries in a column {geometry!r}: join the "
                "boundaries reference source in SQL, or name the column in `geometry`"
            )
        elif column.type not in GEOMETRY:
            problems.append(f"the boundaries in {geometry!r} must be GeoJSON, not {column.type}")
    problems += _spec_columns(spec, columns, "label")
    return problems + _measure(output, spec, columns, "value")


def _measure(
    output: Schema, spec: JsonObject, columns: _Columns, key: str, exclude: str | None = None
) -> list[str]:
    """The number the widget shows: the spec's `key`, else the first measure, else the
    first numeric column, as the widget bundles pick it."""
    named = _text(spec, key)
    if named is not None:
        if not columns:
            return []
        column = columns.get(named)
        if column is None:
            return [f"there is no column {named!r} for `{key}`"]
        if column.type not in NUMERIC:
            return [f"`{key}` needs a number, and {named!r} is {column.type}"]
        return []
    if output.roles.measures or not columns:
        return []
    if any(c.type in NUMERIC and c.name != exclude for c in columns.values()):
        return []
    return [f"it needs a number for `{key}`: a measure role or a numeric column"]


def _spec_columns(spec: JsonObject, columns: _Columns, *keys: str) -> list[str]:
    if not columns:
        return []
    return [
        f"there is no column {name!r} for `{key}`"
        for key in keys
        if (name := _text(spec, key)) is not None and name not in columns
    ]


def _text(spec: JsonObject, key: str) -> str | None:
    value = spec.get(key)
    return value if isinstance(value, str) and value else None


_NEEDS = {
    "value": _value,
    "table": _table,
    "line-chart": _line_chart,
    "map": _map,
    "chart": _chart,
}


def has_bounds(measure: MeasureRole) -> bool:
    return measure.lower is not None or measure.upper is not None


def _grain(grain: object) -> str:
    return f"by {grain}" if grain is not None else "of no fixed length"


def _one_of(types: Iterable[ColumnType]) -> str:
    return " or ".join(sorted(t.value for t in types))
