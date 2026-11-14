"""A rule's condition: a formula tree, checked against the measure's schema and compiled to
SQL (spec: Rules and alert pipelines).

The tree is JSON. Every node has an `id`, unique in the tree, so an interface can address
sub-expressions (a later graph builder can let rules share them), and a `kind`. Composite
nodes keep their operands in `args`, in order:

    {"id": "low", "kind": "compare", "op": "<",
     "args": [{"id": "v", "kind": "column", "column": "value"},
              {"id": "c", "kind": "constant", "value": 80}]}

- `column` (`column`): a column of the measure; its type.
- `constant` (`value`, optional `type`): a number, text, true or false; with `type` "date"
  or "timestamp", an ISO 8601 string.
- `arithmetic` (`op` + - * /, `args` [a, b]): numbers; dividing by zero gives NULL.
- `compare` (`op` < <= > >= = !=, `args` [a, b]): two values of the same type.
- `and`, `or` (`args` [a, b, ...]) and `not` (`args` [a]): conditions.
- `previous` (`args` [a], `periods`, default 1): a, that many periods earlier.
- `change` (`args` [a], `periods`, default 1): a minus a that many periods earlier.
- `rolling_mean` (`args` [a], `periods`): the mean of a over the last n periods, this one
  included; NULL until n periods with a value exist.

The root must be boolean. The time functions need the measure's time role: a period is a
row, and "previous" is the previous row by the time role's start within the same key.

The compiled SQL is one SELECT over `input_0`, the measure, in layers:

1. Values withheld by a measure's `suppressed` flag become NULL, so they feed no time
   function and no comparison.
2. One layer per time function, innermost first, adds a window column partitioned by the
   key columns and ordered by the time start (windows cannot nest in SQL).
3. The condition and each row's recency within its key are computed.
4. The alerting rows are kept: the condition is TRUE (NULL counts as false), the row is its
   key's latest period, and no measure the formula reads is suppressed in it. The helper
   columns are dropped, so the output has the measure's columns.
"""

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from ada.core.models.base import JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import ColumnType, Schema

# Helper columns of the compiled query; measure columns may not use the prefix.
RESERVED_PREFIX = "__ada_"
MAX_NODES = 200
MAX_DEPTH = 32
MAX_PERIODS = 1000
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ValueType(StrEnum):
    NUMBER = "number"
    TEXT = "text"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"


_COLUMN_TYPES = {
    ColumnType.INTEGER: ValueType.NUMBER,
    ColumnType.NUMBER: ValueType.NUMBER,
    ColumnType.TEXT: ValueType.TEXT,
    ColumnType.BOOLEAN: ValueType.BOOLEAN,
    ColumnType.DATE: ValueType.DATE,
    ColumnType.TIMESTAMP: ValueType.TIMESTAMP,
}

ARITHMETIC = ("+", "-", "*", "/")
COMPARISONS = ("<", "<=", ">", ">=", "=", "!=")
TIME_FUNCTIONS = ("previous", "change", "rolling_mean")
_ARITY = {
    "arithmetic": (2, 2),
    "compare": (2, 2),
    "and": (2, None),
    "or": (2, None),
    "not": (1, 1),
    "previous": (1, 1),
    "change": (1, 1),
    "rolling_mean": (1, 1),
}
_FIELDS = {
    "column": {"column"},
    "constant": {"value", "type"},
    "arithmetic": {"op", "args"},
    "compare": {"op", "args"},
    "and": {"args"},
    "or": {"args"},
    "not": {"args"},
    "previous": {"args", "periods"},
    "change": {"args", "periods"},
    "rolling_mean": {"args", "periods"},
}


@dataclass(frozen=True)
class Node:
    """One parsed node. `type` is worked out against the schema when parsing."""

    id: str
    kind: str
    type: ValueType
    args: tuple[Node, ...] = ()
    column: str | None = None
    value: Any = None
    op: str | None = None
    periods: int = 1


@dataclass(frozen=True)
class Compiled:
    """A checked formula: its SQL over `input_0` and the condition in words."""

    sql: str
    condition: str
    # The columns the formula reads, e.g. to know which suppression flags apply.
    columns: frozenset[str]


def compile_rule(formula: JsonObject, schema: Schema, key_columns: tuple[str, ...]) -> Compiled:
    """Check the formula and key columns against the measure's schema and compile them.
    Raises Invalid naming the node at fault, as `Formula node 'id': ...`."""
    check_key_columns(key_columns, schema)
    root = _Parser(schema).parse(formula)
    if root.type is not ValueType.BOOLEAN:
        raise _invalid(root.id, f"the condition must be true or false, not a {root.type}")
    return _Compiler(root, schema, key_columns).compile()


def check_key_columns(key_columns: tuple[str, ...], schema: Schema) -> None:
    if len(set(key_columns)) != len(key_columns):
        raise Invalid("The key columns repeat a column")
    reserved = [c.name for c in schema.columns if c.name.startswith(RESERVED_PREFIX)]
    if reserved:
        raise Invalid(f"Column names starting with {RESERVED_PREFIX} are reserved: {reserved}")
    for name in key_columns:
        column = schema.column(name)
        if column is None:
            raise Invalid(f"The key column {name!r} is not a column of the measure")
        if column.type is ColumnType.JSON:
            raise Invalid(f"The key column {name!r} holds JSON, which cannot identify a row")


def describe(formula: JsonObject, schema: Schema) -> str:
    """The condition in words, e.g. `value < 80 or change(value, 1) <= -5`."""
    return _text(_Parser(schema).parse(formula))


def _invalid(node_id: str, message: str) -> Invalid:
    return Invalid(f"Formula node {node_id!r}: {message}")


class _Parser:
    def __init__(self, schema: Schema) -> None:
        self.schema = schema
        self.ids: set[str] = set()

    def parse(self, raw: object, depth: int = 0) -> Node:
        if not isinstance(raw, dict):
            raise Invalid("A formula node must be an object with an id and a kind")
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not _ID.match(node_id):
            raise Invalid(
                "Every formula node needs an id of 1 to 64 letters, digits, - or _; "
                f"got {node_id!r}"
            )
        if node_id in self.ids:
            raise _invalid(node_id, "the id is used twice")
        self.ids.add(node_id)
        if len(self.ids) > MAX_NODES:
            raise Invalid(f"A formula may have at most {MAX_NODES} nodes")
        if depth > MAX_DEPTH:
            raise _invalid(node_id, f"the formula nests deeper than {MAX_DEPTH} levels")
        kind = raw.get("kind")
        if kind not in _FIELDS:
            raise _invalid(node_id, f"unknown kind {kind!r}; use one of {', '.join(_FIELDS)}")
        unknown = set(raw) - _FIELDS[kind] - {"id", "kind"}
        if unknown:
            raise _invalid(node_id, f"the {kind} node has no {', '.join(sorted(unknown))}")
        args = self._args(node_id, kind, raw, depth)
        match kind:
            case "column":
                return self._column(node_id, raw.get("column"))
            case "constant":
                return _constant(node_id, raw)
            case "arithmetic":
                op = _op(node_id, raw, ARITHMETIC)
                _need(args, ValueType.NUMBER, f"{op} works on numbers")
                return Node(node_id, kind, ValueType.NUMBER, args, op=op)
            case "compare":
                op = _op(node_id, raw, COMPARISONS)
                left, right = args
                if left.type is not right.type:
                    raise _invalid(node_id, f"cannot compare a {left.type} with a {right.type}")
                if left.type is ValueType.BOOLEAN and op not in ("=", "!="):
                    raise _invalid(node_id, f"{op} does not order true and false; use = or !=")
                return Node(node_id, kind, ValueType.BOOLEAN, args, op=op)
            case "and" | "or" | "not":
                _need(args, ValueType.BOOLEAN, f"{kind} works on conditions")
                return Node(node_id, kind, ValueType.BOOLEAN, args)
            case _:
                return self._time_function(node_id, kind, raw, args)

    def _args(self, node_id: str, kind: str, raw: JsonObject, depth: int) -> tuple[Node, ...]:
        if kind not in _ARITY:
            return ()
        args = raw.get("args")
        low, high = _ARITY[kind]
        if not isinstance(args, list):
            raise _invalid(node_id, f"the {kind} node needs its operands in args")
        if len(args) < low or (high is not None and len(args) > high):
            wanted = f"{low}" if low == high else f"at least {low}"
            raise _invalid(node_id, f"the {kind} node takes {wanted} operands, not {len(args)}")
        return tuple(self.parse(arg, depth + 1) for arg in args)

    def _column(self, node_id: str, name: object) -> Node:
        if not isinstance(name, str) or not name:
            raise _invalid(node_id, "a column node needs the column's name")
        column = self.schema.column(name)
        if column is None:
            known = ", ".join(c.name for c in self.schema.columns)
            raise _invalid(node_id, f"{name!r} is not a column of the measure ({known})")
        if column.type not in _COLUMN_TYPES:
            raise _invalid(node_id, f"{name!r} holds {column.type}, which a formula cannot use")
        return Node(node_id, "column", _COLUMN_TYPES[column.type], column=name)

    def _time_function(
        self, node_id: str, kind: str, raw: JsonObject, args: tuple[Node, ...]
    ) -> Node:
        if self.schema.roles.time is None:
            raise _invalid(
                node_id,
                f"{kind} needs to know what a period is, but the measure declares no time role",
            )
        periods = raw.get("periods", 1)
        if (
            not isinstance(periods, int)
            or isinstance(periods, bool)
            or not 1 <= periods <= MAX_PERIODS
        ):
            raise _invalid(node_id, f"periods must be a whole number from 1 to {MAX_PERIODS}")
        (arg,) = args
        if kind == "previous":
            return Node(node_id, kind, arg.type, args, periods=periods)
        _need(args, ValueType.NUMBER, f"{kind} works on numbers")
        return Node(node_id, kind, ValueType.NUMBER, args, periods=periods)


def _op(node_id: str, raw: JsonObject, allowed: tuple[str, ...]) -> str:
    op = raw.get("op")
    if op not in allowed:
        raise _invalid(node_id, f"op must be one of {' '.join(allowed)}, not {op!r}")
    return op


def _need(args: tuple[Node, ...], wanted: ValueType, what: str) -> None:
    for arg in args:
        if arg.type is not wanted:
            raise _invalid(arg.id, f"{what}, but this is a {arg.type}")


def _constant(node_id: str, raw: JsonObject) -> Node:
    value = raw.get("value")
    declared = raw.get("type")
    if declared is not None and declared not in {t.value for t in ValueType}:
        raise _invalid(node_id, f"unknown constant type {declared!r}")
    if isinstance(value, bool):
        inferred = ValueType.BOOLEAN
    elif isinstance(value, int | float):
        if not math.isfinite(value):
            raise _invalid(node_id, "a number must be finite")
        inferred = ValueType.NUMBER
    elif isinstance(value, str):
        inferred = ValueType.TEXT
    else:
        raise _invalid(node_id, "a constant is a number, text, true or false")
    kind = ValueType(declared) if declared is not None else inferred
    if kind in (ValueType.DATE, ValueType.TIMESTAMP):
        if not isinstance(value, str):
            raise _invalid(node_id, f"a {kind} constant is written as an ISO 8601 string")
        try:
            parsed: date = (
                date.fromisoformat(value)
                if kind is ValueType.DATE
                else datetime.fromisoformat(value)
            )
        except ValueError:
            raise _invalid(node_id, f"{value!r} is not an ISO 8601 {kind}") from None
        value = parsed.isoformat()
    elif kind is not inferred:
        raise _invalid(node_id, f"{value!r} is not a {kind}")
    return Node(node_id, "constant", kind, value=value)


class _Compiler:
    def __init__(self, root: Node, schema: Schema, key_columns: tuple[str, ...]) -> None:
        self.root = root
        self.schema = schema
        self.keys = key_columns
        # Time function node id -> its window column, in the order the layers compute them.
        self.windows: dict[str, str] = {}
        self.layers: list[str] = []

    def compile(self) -> Compiled:
        read = frozenset(_columns(self.root))
        start = self.schema.roles.time.start if self.schema.roles.time else None
        steps = [f"{RESERVED_PREFIX}l0 AS (\n{self._unsuppressed()}\n)"]
        # Post-order: an inner time function has its column before the outer one reads it.
        for node in _post_order(self.root):
            if node.kind in TIME_FUNCTIONS:
                name = f"{RESERVED_PREFIX}t{len(self.windows)}"
                expression = self._window(node, start)
                self.windows[node.id] = name
                previous = f"{RESERVED_PREFIX}l{len(steps) - 1}"
                steps.append(
                    f"{RESERVED_PREFIX}l{len(steps)} AS (\n"
                    f"SELECT *, {expression} AS {quote(name)} FROM {previous}\n)"
                )
        condition = self._sql(self.root)
        last = f"{RESERVED_PREFIX}l{len(steps) - 1}"
        alerting, recency = f"{RESERVED_PREFIX}alerting", f"{RESERVED_PREFIX}recency"
        evaluated = [f"({condition}) AS {quote(alerting)}"]
        if start is not None:
            evaluated.append(
                f"row_number() OVER ({self._partition()}ORDER BY {quote(start)} DESC) "
                f"AS {quote(recency)}"
            )
        steps.append(f"{RESERVED_PREFIX}eval AS (\nSELECT *, {', '.join(evaluated)} FROM {last}\n)")
        helpers = [*self.windows.values(), alerting] + ([recency] if start else [])
        where = [f"{quote(alerting)} IS TRUE"]
        if start is not None:
            where.append(f"{quote(recency)} = 1")
        for measure in self.schema.roles.measures:
            if measure.suppressed and _withheld(measure) & read:
                where.append(f"{quote(measure.suppressed)} IS NOT TRUE")
        order = [*self.keys, *([start] if start else [])]
        sql = (
            f"WITH {',\n'.join(steps)}\n"
            f"SELECT * EXCLUDE ({', '.join(quote(h) for h in helpers)})\n"
            f"FROM {RESERVED_PREFIX}eval\n"
            f"WHERE {' AND '.join(where)}"
        )
        if order:
            sql += f"\nORDER BY {', '.join(quote(c) for c in order)}"
        return Compiled(sql=sql, condition=_text(self.root), columns=read)

    def _unsuppressed(self) -> str:
        """The measure with withheld values set to NULL."""
        replaced: dict[str, str] = {}
        for measure in self.schema.roles.measures:
            if measure.suppressed is None:
                continue
            flag = quote(measure.suppressed)
            for name in sorted(_withheld(measure)):
                replaced[name] = f"CASE WHEN {flag} THEN NULL ELSE {quote(name)} END"
        if not replaced:
            return "SELECT * FROM input_0"
        replacements = ", ".join(f"{sql} AS {quote(name)}" for name, sql in replaced.items())
        return f"SELECT * REPLACE ({replacements}) FROM input_0"

    def _partition(self) -> str:
        if not self.keys:
            return ""
        return f"PARTITION BY {', '.join(quote(k) for k in self.keys)} "

    def _window(self, node: Node, start: str | None) -> str:
        assert start is not None  # The parser rejects time functions without a time role.
        (arg,) = node.args
        value = self._sql(arg)
        order = f"{self._partition()}ORDER BY {quote(start)}"
        n = node.periods
        match node.kind:
            case "previous":
                return f"lag({value}, {n}) OVER ({order})"
            case "change":
                return f"({value} - lag({value}, {n}) OVER ({order}))"
            case _:
                # Only a full window counts: a missing or withheld period makes the mean
                # unknown rather than a mean of fewer periods.
                frame = f"{order} ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW"
                return (
                    f"CASE WHEN count({value}) OVER ({frame}) = {n} "
                    f"THEN avg({value}) OVER ({frame}) END"
                )

    def _sql(self, node: Node) -> str:
        if node.id in self.windows:
            return quote(self.windows[node.id])
        match node.kind:
            case "column":
                assert node.column is not None
                return quote(node.column)
            case "constant":
                return _literal(node)
            case "arithmetic":
                left, right = (self._sql(arg) for arg in node.args)
                if node.op == "/":
                    # Dividing by zero is unknown, not an error that stops every check.
                    return f"({left} / NULLIF({right}, 0))"
                return f"({left} {node.op} {right})"
            case "compare":
                left, right = (self._sql(arg) for arg in node.args)
                op = "<>" if node.op == "!=" else node.op
                return f"({left} {op} {right})"
            case "and" | "or":
                joined = f" {node.kind.upper()} ".join(self._sql(arg) for arg in node.args)
                return f"({joined})"
            case "not":
                return f"(NOT {self._sql(node.args[0])})"
        raise AssertionError(f"Time function {node.id} was not compiled into a layer")


def _literal(node: Node) -> str:
    value = node.value
    match node.type:
        case ValueType.BOOLEAN:
            return "TRUE" if value else "FALSE"
        case ValueType.NUMBER:
            # DOUBLE throughout, so integer columns and constants compare and divide alike.
            return f"CAST({value!r} AS DOUBLE)"
        case ValueType.TEXT:
            return _string(value)
        case ValueType.DATE:
            return f"DATE {_string(value)}"
        case ValueType.TIMESTAMP:
            return f"TIMESTAMP {_string(value)}"


def _string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _withheld(measure: Any) -> set[str]:
    """The columns a measure's suppression flag withholds."""
    return {name for name in (measure.value, measure.lower, measure.upper) if name}


def _post_order(node: Node) -> list[Node]:
    return [descendant for arg in node.args for descendant in _post_order(arg)] + [node]


def _columns(node: Node) -> set[str]:
    own = {node.column} if node.column else set()
    return own.union(*(_columns(arg) for arg in node.args))


# How tightly each operator binds, for the text form: a child that binds looser than its
# parent is parenthesised. Atoms (columns, constants, functions) bind tightest.
_PRECEDENCE = {"or": 1, "and": 2, "not": 3, "compare": 4, "+": 5, "-": 5, "*": 6, "/": 6}
_ATOM = 7


def _precedence(node: Node) -> int:
    if node.kind == "arithmetic":
        assert node.op is not None
        return _PRECEDENCE[node.op]
    return _PRECEDENCE.get(node.kind, _ATOM)


def _text(node: Node) -> str:
    """The node as a person reads it, with only the parentheses the meaning needs."""
    match node.kind:
        case "column":
            assert node.column is not None
            plain = re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", node.column)
            return node.column if plain else f"[{node.column}]"
        case "constant":
            if node.type is ValueType.BOOLEAN:
                return "true" if node.value else "false"
            if node.type in (ValueType.NUMBER, ValueType.TEXT):
                return json.dumps(node.value)
            return f"{node.type} {node.value}"
        case "previous" | "change" | "rolling_mean":
            periods = "1 period" if node.periods == 1 else f"{node.periods} periods"
            return f"{node.kind}({_text(node.args[0])}, {periods})"
        case "not":
            # Anything but a single value is parenthesised: not (a < b) reads unambiguously.
            return f"not {_operand(node.args[0], _ATOM, right=False)}"
    own = _precedence(node)
    joiner = f" {node.kind} " if node.kind in ("and", "or") else f" {node.op} "
    return joiner.join(_operand(arg, own, right=index > 0) for index, arg in enumerate(node.args))


def _operand(node: Node, parent: int, right: bool) -> str:
    text = _text(node)
    precedence = _precedence(node)
    # a - (b - c) and a < (b < c) keep their parentheses; a and (b and c) need none.
    if precedence < parent or (right and precedence == parent and node.kind not in ("and", "or")):
        return f"({text})"
    return text
