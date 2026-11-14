"""The settings of widget types beyond the roles they need: a chart's Vega-Lite spec, a
table's labels and formats, a value's comparison. Each check returns the problems it found,
so `check_widget` (core/services/schema/roles.py) names them all at once. Columns that are
not known yet (an empty mapping) are not checked."""

from collections.abc import Mapping
from typing import Any

from ada.core.models.base import JsonObject
from ada.core.models.schema import Column, ColumnType

NUMBER_FORMATS = ("integer", "number", "percent", "plain")
_NUMERIC = frozenset({ColumnType.INTEGER, ColumnType.NUMBER})

# The views a Vega-Lite spec can be; one of these keys must be at its top.
CHART_VIEWS = ("mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat")
# Keys refused anywhere in a chart spec: the widget puts the operator's rows in as the only
# data, and a chart loads nothing and links nowhere.
_REFUSED = {
    "data": "ADA puts the operator's rows in as the data; compute what you need in a transform",
    "datasets": "ADA puts the operator's rows in as the data",
    "url": "a chart loads nothing from elsewhere",
    "href": "a chart links nowhere",
    "usermeta": "a chart carries no extra metadata",
}

type _Columns = Mapping[str, Column]


def chart_problems(spec: JsonObject) -> list[str]:
    """A Vega-Lite spec without data: one of the views at its top, and none of the refused
    keys at any depth. Whether it compiles is checked by the widget when it renders."""
    problems: list[str] = []
    if not any(key in spec for key in CHART_VIEWS):
        problems.append(
            "a chart spec is a Vega-Lite spec with a "
            + ", ".join(f"`{key}`" for key in CHART_VIEWS[:-1])
            + f" or `{CHART_VIEWS[-1]}` at its top"
        )
    for path, key in _refused_keys(spec, ""):
        problems.append(f"`{path}` is not allowed: {_REFUSED[key]}")
    return problems


def _refused_keys(node: Any, path: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key in _REFUSED:
                found.append((here, key))
            else:
                found += _refused_keys(value, here)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found += _refused_keys(item, f"{path}[{index}]")
    return found


def table_problems(spec: JsonObject, columns: _Columns) -> list[str]:
    """`labels` maps columns to header text, `format` columns to a number format, and
    `decimals` is a small whole number."""
    problems: list[str] = []
    labels = spec.get("labels")
    if labels is not None:
        if not isinstance(labels, dict) or not all(
            isinstance(text, str) for text in labels.values()
        ):
            problems.append('`labels` must map column names to header text: {"column": "Header"}')
        else:
            problems += _known(labels, columns, "labels")
    formats = spec.get("format")
    if formats is not None:
        if not isinstance(formats, dict):
            problems.append(
                '`format` must map column names to a number format: {"column": "percent"}'
            )
        else:
            problems += _known(formats, columns, "format")
            problems += [
                f"`format` of {name!r} must be {_formats()}, not {value!r}"
                for name, value in formats.items()
                if value not in NUMBER_FORMATS
            ]
    return problems + _decimals(spec)


def value_problems(spec: JsonObject, columns: _Columns) -> list[str]:
    """`format` is one number format; `compare_to` a numeric column or a number."""
    problems: list[str] = []
    format = spec.get("format")
    if format is not None and format not in NUMBER_FORMATS:
        problems.append(f"`format` must be {_formats()}, not {format!r}")
    compare_to = spec.get("compare_to")
    if isinstance(compare_to, str):
        column = columns.get(compare_to)
        if columns and column is None:
            problems.append(f"there is no column {compare_to!r} for `compare_to`")
        elif column is not None and column.type not in _NUMERIC:
            problems.append(f"`compare_to` needs a number, and {compare_to!r} is {column.type}")
    elif compare_to is not None and (
        isinstance(compare_to, bool) or not isinstance(compare_to, int | float)
    ):
        problems.append("`compare_to` must be a column name or a number")
    return problems + _decimals(spec)


def _known(mapping: dict[str, Any], columns: _Columns, key: str) -> list[str]:
    if not columns:
        return []
    return [f"there is no column {name!r} for `{key}`" for name in mapping if name not in columns]


def _decimals(spec: JsonObject) -> list[str]:
    decimals = spec.get("decimals")
    if decimals is None:
        return []
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 10:
        return ["`decimals` must be a whole number from 0 to 10"]
    return []


def _formats() -> str:
    return ", ".join(f'"{name}"' for name in NUMBER_FORMATS[:-1]) + f' or "{NUMBER_FORMATS[-1]}"'
