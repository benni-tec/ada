"""The formula tree of alert rules: validation against the measure's schema, and the SQL it
compiles to, run on DuckDB the way a fused query runs it (input_0 is the measure)."""

from collections.abc import Sequence
from datetime import date
from typing import Any

import duckdb
import pytest

from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, MeasureRole, Roles, Schema, TimeRole
from ada.core.services.alerts.formula import compile_rule, describe

SERIES = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="start", type=ColumnType.DATE),
        Column(name="end", type=ColumnType.DATE),
        Column(name="value", type=ColumnType.NUMBER),
        Column(name="count", type=ColumnType.INTEGER),
        Column(name="hidden", type=ColumnType.BOOLEAN),
        Column(name="extra", type=ColumnType.JSON),
    ),
    roles=Roles(
        time=TimeRole(start="start", end="end"),
        measures=(MeasureRole(value="value", suppressed="hidden"),),
    ),
)
FLAT = Schema(
    columns=(
        Column(name="region", type=ColumnType.TEXT),
        Column(name="value", type=ColumnType.NUMBER),
    )
)
KEY = ("region",)


# Builders, so each test states only its tree.


def col(name: str, id: str | None = None) -> dict[str, Any]:
    return {"id": id or f"col-{name}", "kind": "column", "column": name}


def const(value: object, id: str = "const", **extra: Any) -> dict[str, Any]:
    return {"id": id, "kind": "constant", "value": value, **extra}


def cmp(op: str, left: dict[str, Any], right: dict[str, Any], id: str = "cmp") -> dict[str, Any]:
    return {"id": id, "kind": "compare", "op": op, "args": [left, right]}


def arith(op: str, left: dict[str, Any], right: dict[str, Any], id: str = "ar") -> dict[str, Any]:
    return {"id": id, "kind": "arithmetic", "op": op, "args": [left, right]}


def fn(kind: str, arg: dict[str, Any], periods: int = 1, id: str | None = None) -> dict[str, Any]:
    return {"id": id or kind, "kind": kind, "periods": periods, "args": [arg]}


def logic(kind: str, *args: dict[str, Any], id: str | None = None) -> dict[str, Any]:
    return {"id": id or kind, "kind": kind, "args": list(args)}


# Data: (region, year, value, hidden)

Row = tuple[str, int, float | None, bool]


def alerting(
    formula: dict[str, Any],
    rows: Sequence[Row],
    key: tuple[str, ...] = KEY,
    schema: Schema = SERIES,
) -> list[tuple[Any, ...]]:
    """The (region, year) of the rows that alert."""
    compiled = compile_rule(formula, schema, key)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            'CREATE TABLE measure (region VARCHAR, start DATE, "end" DATE, value DOUBLE, '
            "count BIGINT, hidden BOOLEAN, extra JSON)"
        )
        for region, year, value, hidden in rows:
            connection.execute(
                "INSERT INTO measure VALUES (?, ?, ?, ?, 1, ?, '{}')",
                [region, date(year, 1, 1), date(year, 12, 31), value, hidden],
            )
        if schema is FLAT:
            source = "SELECT region, value FROM measure"
        else:
            source = "SELECT * FROM measure"
        relation = connection.sql(f"WITH input_0 AS ({source}) SELECT * FROM (\n{compiled.sql}\n)")
        names = relation.columns
        result = relation.fetchall()
    expected = [c.name for c in schema.columns]
    assert names == expected, "the alerting rows have exactly the measure's columns"
    if schema is FLAT:
        return [(row[0], row[1]) for row in result]
    return [(row[0], row[1].year) for row in result]


def series(region: str, *values: float | None, first: int = 2020) -> list[Row]:
    return [(region, first + i, value, value is None) for i, value in enumerate(values)]


# Validation


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        (cmp("<", col("nope"), const(1)), "Formula node 'col-nope': 'nope' is not a column"),
        (
            cmp("<", col("region"), const(1)),
            "Formula node 'cmp': cannot compare a text with a number",
        ),
        (arith("+", col("region"), const(1)), "Formula node 'col-region': \\+ works on numbers"),
        (col("value"), "Formula node 'col-value': the condition must be true or false"),
        (logic("and", col("hidden"), col("value")), "Formula node 'col-value': and works on"),
        (logic("not", col("hidden"), col("hidden", "h2")), "the not node takes 1 operands, not 2"),
        (logic("or", col("hidden")), "the or node takes at least 2 operands"),
        (cmp("<", col("hidden"), col("hidden", "h2")), "does not order true and false"),
        (cmp("<", col("extra"), const(1)), "'extra' holds json"),
        ({"id": "x", "kind": "magic"}, "Formula node 'x': unknown kind 'magic'"),
        ({"kind": "column", "column": "value"}, "needs an id"),
        ({"id": "bad id", "kind": "column", "column": "value"}, "needs an id"),
        (
            cmp("<", col("value", "same"), const(1, "same")),
            "Formula node 'same': the id is used twice",
        ),
        (cmp("~", col("value"), const(1)), "op must be one of"),
        (cmp("<", col("value"), const(None)), "a constant is a number"),
        (cmp("<", col("value"), const(float("inf"))), "must be finite"),
        (cmp("<", col("start"), const("2024-13-01", type="date")), "not an ISO 8601 date"),
        (cmp("<", col("value"), const("1", type="number")), "'1' is not a number"),
        (cmp("<", fn("change", col("value"), periods=0), const(1)), "periods must be"),
        (cmp("<", fn("rolling_mean", col("region")), const(1)), "rolling_mean works on numbers"),
        ({"id": "x", "kind": "column", "column": "value", "op": "<"}, "the column node has no op"),
        ([], "must be an object"),
    ],
)
def test_invalid_formulas_name_the_node_at_fault(formula: Any, message: str) -> None:
    with pytest.raises(Invalid, match=message):
        compile_rule(formula, SERIES, KEY)


def test_time_functions_need_a_time_role() -> None:
    formula = cmp("<", fn("previous", col("value")), const(1))
    with pytest.raises(Invalid, match="Formula node 'previous': .*declares no time role"):
        compile_rule(formula, FLAT, KEY)


@pytest.mark.parametrize(
    ("key", "message"),
    [
        (("nope",), "The key column 'nope' is not a column"),
        (("extra",), "holds JSON"),
        (("region", "region"), "repeat"),
    ],
)
def test_key_columns_must_be_columns(key: tuple[str, ...], message: str) -> None:
    with pytest.raises(Invalid, match=message):
        compile_rule(cmp("<", col("value"), const(1)), SERIES, key)


def test_reserved_column_names_are_rejected() -> None:
    schema = Schema(columns=(Column(name="__ada_t0", type=ColumnType.NUMBER),))
    with pytest.raises(Invalid, match="reserved"):
        compile_rule(cmp("<", col("__ada_t0"), const(1)), schema, ())


def test_large_and_deep_formulas_are_rejected() -> None:
    wide = logic(
        "and", *[cmp("<", col("value", f"v{i}"), const(1, f"c{i}"), f"p{i}") for i in range(80)]
    )
    with pytest.raises(Invalid, match="at most 200 nodes"):
        compile_rule(wide, SERIES, KEY)
    deep: dict[str, Any] = col("hidden", "leaf")
    for i in range(40):
        deep = logic("not", deep, id=f"n{i}")
    with pytest.raises(Invalid, match="nests deeper"):
        compile_rule(deep, SERIES, KEY)


def test_the_condition_reads_as_text() -> None:
    formula = logic(
        "or",
        cmp("<", col("value"), const(80), id="low"),
        cmp("<=", fn("change", col("value", "v2"), periods=2), const(-5, "c5"), id="drop"),
        logic("not", col("hidden"), id="shown"),
    )
    assert describe(formula, SERIES) == (
        "value < 80 or change(value, 2 periods) <= -5 or not hidden"
    )
    assert compile_rule(formula, SERIES, KEY).condition == describe(formula, SERIES)
    plus = arith("+", col("value"), const(1, "one"), id="plus")
    nested = cmp("<", arith("*", plus, const(2), id="times"), const(3, "c3"))
    assert describe(nested, SERIES) == "(value + 1) * 2 < 3"
    minus = arith("-", col("value"), arith("-", col("count"), const(1, "one"), id="in"), id="out")
    assert describe(cmp(">", minus, const(0)), SERIES) == "value - (count - 1) > 0"


# Compilation: each node type


def test_comparisons_and_constants() -> None:
    rows = series("north", 90, 70) + series("south", 85, 95)
    assert alerting(cmp("<", col("value"), const(80)), rows) == [("north", 2021)]
    assert alerting(cmp(">=", col("value"), const(95)), rows) == [("south", 2021)]
    assert alerting(cmp("=", col("region"), const("south")), rows) == [("south", 2021)]
    assert alerting(cmp("!=", col("region"), const("south")), rows) == [("north", 2021)]
    # Integer columns compare with numbers.
    assert alerting(cmp("=", col("count"), const(1)), rows) == [("north", 2021), ("south", 2021)]
    after = cmp(">", col("start"), const("2021-06-01", type="date"))
    assert alerting(after, rows) == []
    # Text with a quote is a literal, not SQL.
    assert alerting(cmp("=", col("region"), const("x' OR 1=1 --")), rows) == []


def test_arithmetic() -> None:
    rows = series("north", 10) + series("south", 30)
    doubled = cmp(">", arith("*", col("value"), const(2, "two")), const(50))
    assert alerting(doubled, rows) == [("south", 2020)]
    minus = cmp("<", arith("-", col("value"), const(20, "c20")), const(0))
    assert alerting(minus, rows) == [("north", 2020)]
    share = cmp(">", arith("/", col("value"), const(60, "c60")), const(0.4))
    assert alerting(share, rows) == [("south", 2020)]
    # Dividing by zero is unknown and never alerts; it does not fail the check.
    by_zero = cmp(">", arith("/", col("value"), const(0, "zero")), const(0))
    assert alerting(by_zero, rows) == []


def test_and_or_not() -> None:
    rows = series("north", 10) + series("south", 30) + series("east", 50)
    low = cmp("<", col("value"), const(20, "c20"), id="low")
    high = cmp(">", col("value", "v2"), const(40, "c40"), id="high")
    assert alerting(logic("or", low, high), rows) == [("east", 2020), ("north", 2020)]
    assert alerting(logic("and", low, high), rows) == []
    assert alerting(logic("not", logic("or", low, high)), rows) == [("south", 2020)]


def test_previous_period_is_the_previous_row_of_the_same_key() -> None:
    # Rows arrive out of order and interleaved; the window orders them by period start.
    rows = [
        ("north", 2022, 70.0, False),
        ("south", 2021, 60.0, False),
        ("north", 2021, 90.0, False),
        ("south", 2022, 65.0, False),
    ]
    fell = cmp("<", col("value"), fn("previous", col("value", "v2")))
    assert alerting(fell, rows) == [("north", 2022)]
    two_back = [*series("north", 90, 50, 60), *series("south", 70, 10, 80)]
    below_two_ago = cmp("<", col("value"), fn("previous", col("value", "v2"), periods=2))
    assert alerting(below_two_ago, two_back) == [("north", 2022)]


def test_change_over_n_periods() -> None:
    rows = series("north", 80, 79, 74) + series("south", 80, 82, 81)
    dropped = cmp("<=", fn("change", col("value")), const(-5))
    assert alerting(dropped, rows) == [("north", 2022)]
    dropped_over_two = cmp("<=", fn("change", col("value"), periods=2), const(-5))
    assert alerting(dropped_over_two, rows) == [("north", 2022)]
    # Without enough history the change is unknown, which does not alert.
    assert alerting(cmp("<", fn("change", col("value"), periods=5), const(0)), rows) == []


def test_rolling_mean_needs_a_full_window() -> None:
    rows = series("north", 90, 60, 60) + series("south", 60, 60)
    below = cmp("<", fn("rolling_mean", col("value"), periods=3), const(75))
    # north: (90 + 60 + 60) / 3 = 70. south has only two periods, so no mean yet.
    assert alerting(below, rows) == [("north", 2022)]


def test_time_functions_nest() -> None:
    # The change of the change: the drop got steeper.
    rows = series("north", 100, 98, 90) + series("south", 100, 90, 85)
    steeper = cmp("<", fn("change", fn("change", col("value"), id="inner"), id="outer"), const(0))
    assert alerting(steeper, rows) == [("north", 2022)]
    # A window over an expression that holds another window.
    mixed = cmp(
        "<",
        fn(
            "previous",
            arith("-", col("value"), fn("previous", col("value", "v2"), id="p1")),
            id="p2",
        ),
        const(-5),
    )
    # The step before the latest: north -2, south -10.
    assert alerting(mixed, rows) == [("south", 2022)]


def test_only_each_keys_latest_period_alerts() -> None:
    # north was low in 2020 only; south's data ends a year earlier and is low in its last.
    rows = series("north", 10, 90, 90) + series("south", 90, 10)
    assert alerting(cmp("<", col("value"), const(50)), rows) == [("south", 2021)]


def test_without_a_key_the_whole_measure_is_one_series() -> None:
    rows = [("north", 2020, 90.0, False), ("south", 2021, 70.0, False)]
    fell = cmp("<", fn("change", col("value")), const(0))
    assert alerting(fell, rows, key=()) == [("south", 2021)]


def test_without_a_time_role_every_row_is_evaluated() -> None:
    rows = series("north", 10, 90) + series("south", 90)
    assert alerting(cmp("<", col("value"), const(50)), rows, schema=FLAT) == [("north", 10.0)]


def test_suppressed_values_never_alert() -> None:
    rows = [*series("north", 80, None), *series("south", 90, 40)]
    # Withheld values are NULL in the data; a NOT around them must still not alert.
    unknown = logic("not", cmp(">=", col("value"), const(50)))
    assert alerting(unknown, rows) == [("south", 2021)]
    # Even when the condition does not depend on the value, a row whose measure the
    # formula reads and is withheld does not alert.
    either = logic(
        "or",
        cmp("<", col("value"), const(50), id="low"),
        cmp("=", col("region"), const("north", "n"), id="north"),
    )
    assert alerting(either, rows) == [("south", 2021)]


def test_suppressed_values_feed_no_time_function() -> None:
    # The flag withholds the value even where the data still carries one.
    rows: list[Row] = [
        ("north", 2020, 99.0, True),
        ("north", 2021, 60.0, False),
        ("south", 2020, 90.0, False),
        ("south", 2021, 60.0, False),
    ]
    dropped = cmp("<", fn("change", col("value")), const(-10))
    assert alerting(dropped, rows) == [("south", 2021)]
