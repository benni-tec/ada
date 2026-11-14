"""The settings of widget types beyond the roles they need: a chart's Vega-Lite spec, a
table's labels and formats, a value's comparison, a custom widget's code. Each check returns
the problems it found, so `check_widget` (core/services/schema/roles.py) and the widget
service name them all at once. Columns that are not known yet (an empty mapping) are not
checked."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
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


# A custom widget: an ES module that draws, its CSS, and the libraries it may use. The
# frame it runs in has no network and no ADA origin; these checks name an attempt early.
CUSTOM = "custom"
CUSTOM_KEYS = ("code", "css", "libraries")
CUSTOM_LIBRARIES = ("d3", "vega-lite")
MAX_CUSTOM_BYTES = 64 * 1024
# More number literals than this in one array literal is data written into the code.
MAX_ARRAY_NUMBERS = 12

_NO_NETWORK = "a custom widget has no network or storage; its data comes from its inputs"
_NO_LOADING = "a custom widget loads no code; the libraries it lists come in `ada.libraries`"
_NO_OUTSIDE = "a custom widget draws only inside its own frame"

# Refused anywhere in the code, comments and strings included: (what, pattern, why).
_REFUSED_CODE = tuple(
    (label, re.compile(pattern), reason)
    for label, pattern, reason in (
        ("fetch", r"\bfetch\b", _NO_NETWORK),
        ("XMLHttpRequest", r"\bXMLHttpRequest\b", _NO_NETWORK),
        ("WebSocket", r"\bWebSocket\b", _NO_NETWORK),
        ("EventSource", r"\bEventSource\b", _NO_NETWORK),
        ("sendBeacon", r"\bsendBeacon\b", _NO_NETWORK),
        ("importScripts", r"\bimportScripts\b", _NO_NETWORK),
        ("document.cookie", r"\bdocument\s*\.\s*cookie\b", _NO_NETWORK),
        ("localStorage", r"\blocalStorage\b", _NO_NETWORK),
        ("sessionStorage", r"\bsessionStorage\b", _NO_NETWORK),
        ("indexedDB", r"\bindexedDB\b", _NO_NETWORK),
        ("import(", r"\bimport\s*\(", _NO_LOADING),
        ("import", r"(?m)(?:^|;)\s*import\b(?!\s*[(.])", _NO_LOADING),
        ("export … from", r"\bexport\s*(?:\*|\{[^}]*\})\s*from\b", _NO_LOADING),
        ("eval", r"\beval\b", _NO_LOADING),
        ("Function(", r"\bFunction\s*\(", _NO_LOADING),
        ("window.parent", r"\b(?:window|self|globalThis)\s*\.\s*parent\b", _NO_OUTSIDE),
        ("window.top", r"\b(?:window|self|globalThis)\s*\.\s*top\b", _NO_OUTSIDE),
        # The globals, not a property of that name (a d3 hierarchy node's `d.parent`).
        ("parent.", r"(?<![\w$.])parent\s*\.", _NO_OUTSIDE),
        ("top.", r"(?<![\w$.])top\s*\.", _NO_OUTSIDE),
        ("opener", r"\bopener\b", _NO_OUTSIDE),
    )
)
_ADDRESS = re.compile(r"https?://[^\s'\"`)]*")
# SVG and MathML name their namespaces with these; they load nothing.
_NAMESPACE = "http://www.w3.org/"
_CSS_IMPORT = re.compile(r"@import\b", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*['\"]?\s*https?://", re.IGNORECASE)
_DEFAULT_EXPORT = re.compile(r"\bexport\s+default\b")
_NUMBER = re.compile(
    r"(?<![\w$.])(?:0[xXbBoO][\da-fA-F_]+|\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?"
    r"|\.\d[\d_]*(?:[eE][+-]?\d+)?)n?(?![\w$])"
)
# Words after which `[` opens an array and `/` a regular expression.
_KEYWORDS = frozenset(
    "return typeof case do else in of new delete void throw yield await instanceof".split()
)


def custom_problems(spec: JsonObject) -> list[str]:
    """A custom widget's spec: `code`, an ES module with a default export that reaches for
    nothing outside its frame and has no data written into it; `css` without imports or
    addresses; `libraries` from the two the frame provides."""
    problems: list[str] = []
    unknown = sorted(set(spec) - set(CUSTOM_KEYS))
    if unknown:
        problems.append(
            "a custom spec holds only `code`, `css` and `libraries`, not "
            + ", ".join(f"`{key}`" for key in unknown)
        )
    code = spec.get("code")
    if not isinstance(code, str) or not code.strip():
        problems.append(
            "`code` is required: an ES module whose default export draws, "
            "`export default function render(root, data, ada) { ... }`"
        )
        code = ""
    elif not _DEFAULT_EXPORT.search(code):
        problems.append(
            "`code` needs a default export: `export default function render(root, data, ada)`"
        )
    css = spec.get("css") or ""
    if not isinstance(css, str):
        problems.append("`css` must be a string of CSS")
        css = ""
    size = len((code + css).encode())
    if size > MAX_CUSTOM_BYTES:
        problems.append(
            f"`code` and `css` are {size:,} bytes together; at most {MAX_CUSTOM_BYTES:,} (64 KB)"
        )
    libraries = spec.get("libraries") or []
    if not isinstance(libraries, list) or not all(isinstance(name, str) for name in libraries):
        problems.append('`libraries` must be a list of names, e.g. ["d3"]')
    elif unknown_libraries := [name for name in libraries if name not in CUSTOM_LIBRARIES]:
        problems.append(
            '`libraries` may name only "d3" and "vega-lite", not '
            + ", ".join(repr(name) for name in unknown_libraries)
        )
    return problems + _code_problems(code) + _css_problems(css)


def _code_problems(code: str) -> list[str]:
    found: dict[str, list[str]] = {}
    for label, pattern, reason in _REFUSED_CODE:
        match = pattern.search(code)
        if match is not None:
            found.setdefault(reason, []).append(f"`{label}` (line {_line(code, match.start())})")
    problems = [
        f"`code` uses {', '.join(names)}, refused anywhere in the code, comments included: "
        + reason
        for reason, names in found.items()
    ]
    addresses = [
        f"{match.group()[:60]} (line {_line(code, match.start())})"
        for match in _ADDRESS.finditer(code)
        if not match.group().startswith(_NAMESPACE)
    ]
    if addresses:
        more = f" and {len(addresses) - 3} more" if len(addresses) > 3 else ""
        problems.append(
            f"`code` names web addresses: {', '.join(addresses[:3])}{more}; a custom widget "
            f"loads nothing and links nowhere (only {_NAMESPACE}… namespaces may appear)"
        )
    problems += [
        f"`code` line {line}: an array literal of {count} numbers; data comes from the "
        "widget's inputs, not from its code"
        for line, count in _number_arrays(code)
    ]
    return problems


def _css_problems(css: str) -> list[str]:
    problems: list[str] = []
    if _CSS_IMPORT.search(css):
        problems.append("`css` may not use `@import`: a custom widget loads nothing")
    if _CSS_URL.search(css):
        problems.append("`css` may not use `url(` with an http(s) address: it loads nothing")
    return problems


def _number_arrays(code: str) -> list[tuple[int, int]]:
    """The array literals holding more than MAX_ARRAY_NUMBERS number literals, nested ones
    included, as (line, count); of nested offenders only the outermost."""
    tokens = _tokens(code)
    numbers = [match.start() for match in _NUMBER.finditer(tokens)]
    arrays: list[tuple[int, int]] = []
    opened: list[tuple[int, bool]] = []
    for index, char in enumerate(tokens):
        if char == "[":
            opened.append((index, _starts_value(tokens, index)))
        elif char == "]" and opened:
            start, literal = opened.pop()
            if literal:
                arrays.append((start, index))
    found: list[tuple[int, int]] = []
    reported_until = -1
    for start, end in sorted(arrays):
        if start < reported_until:
            continue
        count = bisect_right(numbers, end) - bisect_left(numbers, start)
        if count > MAX_ARRAY_NUMBERS:
            found.append((_line(code, start), count))
            reported_until = end
    return found


def _tokens(code: str) -> str:
    """The code with comments blanked, and strings, template literals and regular
    expressions filled with `_`, each in its place with its newlines kept, so that what is
    left are the tokens around them."""
    out = list(code)

    def fill(start: int, end: int, char: str) -> None:
        for index in range(start, end):
            if out[index] != "\n":
                out[index] = char

    index, length = 0, len(code)
    while index < length:
        char = code[index]
        if code.startswith("//", index):
            end = code.find("\n", index)
            end = length if end == -1 else end
            fill(index, end, " ")
        elif code.startswith("/*", index):
            end = code.find("*/", index + 2)
            end = length if end == -1 else end + 2
            fill(index, end, " ")
        elif char in "'\"`":
            end = _string_end(code, index)
            fill(index, end, "_")
        elif char == "/" and _starts_value(out, index):
            end = _regex_end(code, index)
            fill(index, end, "_")
        else:
            end = index + 1
        index = end
    return "".join(out)


def _string_end(code: str, start: int) -> int:
    quote, index = code[start], start + 1
    while index < len(code):
        char = code[index]
        if char == "\\":
            index += 2
        elif char == quote:
            return index + 1
        elif char == "\n" and quote != "`":
            return index
        else:
            index += 1
    return len(code)


def _regex_end(code: str, start: int) -> int:
    index, in_class = start + 1, False
    while index < len(code):
        char = code[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            return index
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            index += 1
            while index < len(code) and (code[index].isalnum() or code[index] == "_"):
                index += 1
            return index
        index += 1
    return len(code)


def _starts_value(tokens: Sequence[str], index: int) -> bool:
    """Whether the `[` or `/` at `index` starts a value (an array literal, a regular
    expression) rather than indexing or dividing what comes before it."""
    before = index - 1
    while before >= 0 and tokens[before].isspace():
        before -= 1
    if before < 0:
        return True
    previous = tokens[before]
    if previous in ")]_":
        return False
    if previous.isalnum() or previous == "$":
        start = before
        while start > 0 and (tokens[start - 1].isalnum() or tokens[start - 1] in "_$"):
            start -= 1
        return "".join(tokens[start : before + 1]) in _KEYWORDS
    return True


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1
