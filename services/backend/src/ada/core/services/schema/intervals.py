"""The guard on confidence intervals: they do not survive aggregation.

The rule. A transform whose SQL aggregates rows may not declare a measure with bounds.
Aggregating means grouping (GROUP BY, HAVING), an aggregate function or a window over
rows (avg, sum, max ... OVER), or removing duplicates (DISTINCT, UNION without ALL), in
any part of the query that produces the output rows: the main query, its CTEs, the
subqueries and joins it reads from. A subquery that only filters, such as
`WHERE period_end = (SELECT max(period_end) FROM input_0)`, does not count: the rows that
pass keep their own values and bounds.

Why refuse instead of trusting the SQL. The interval of an average is not the average of
the intervals, nor their minimum and maximum; it needs the underlying counts or variances
and a method. SQL can compute one, but the platform cannot tell a correct computation
from `avg(lower)`, so bounds after aggregation come only from a statistic operator that
computes them. Declaring the measure without `lower` and `upper` is always allowed: the
widget then draws no band instead of a wrong one. Filters, joins, projections and
arithmetic per row keep the bounds, so declaring them there is fine.

DuckDB parses the SQL (json_serialize_sql through the analysis store) and this module
reads the syntax tree; the transform's SQL is DuckDB's dialect anyway.
"""

import json
from typing import Any

from ada.core.models.analysis import Query
from ada.core.models.errors import Invalid
from ada.core.models.schema import Roles
from ada.core.ports.analysis import AnalysisStore
from ada.core.services.schema.roles import has_bounds

_PARSE = (
    "SELECT json_serialize_sql({sql}) AS ast, "
    "(SELECT list(DISTINCT lower(function_name)) FROM duckdb_functions() "
    "WHERE function_type = 'aggregate') AS aggregates"
)


async def check_bounds(store: AnalysisStore, sql: str, roles: Roles) -> None:
    """Raises Invalid when the transform declares a measure with bounds and aggregates."""
    bounded = [measure.value for measure in roles.measures if has_bounds(measure)]
    if not bounded:
        return
    reason = await aggregation(store, sql)
    if reason is None:
        return
    names = ", ".join(repr(name) for name in bounded)
    raise Invalid(
        f"The transform aggregates ({reason}), so the bounds declared for {names} would no "
        "longer be a confidence interval of the aggregated value. Declare the measure "
        "without lower and upper (the widget then shows no band), or keep the rows "
        "unaggregated; recomputing an interval is a statistic operator's job."
    )


async def aggregation(store: AnalysisStore, sql: str) -> str | None:
    """What makes the query aggregate its rows, e.g. "GROUP BY" or "avg()"; None when
    every output row is an input row, filtered, joined or computed row by row."""
    literal = "'" + sql.replace("'", "''") + "'"
    rows = await store.run(Query(sql=_PARSE.format(sql=literal)), 1)
    try:
        [(ast_text, names)] = rows.rows
        ast = json.loads(str(ast_text))
        statements = ast["statements"]
        aggregates = {str(name) for name in names or ()}
    except (ValueError, TypeError, KeyError) as error:
        raise Invalid(f"Could not tell whether the transform aggregates: {error}") from None
    if ast.get("error") or len(statements) != 1:
        raise Invalid(f"Could not parse the transform: {ast.get('error_message', '')}")
    return _query(statements[0]["node"], aggregates)


def _query(node: dict[str, Any] | None, aggregates: set[str]) -> str | None:
    if not node:
        return None
    for cte in (node.get("cte_map") or {}).get("map") or []:
        if found := _query(cte["value"]["query_node"], aggregates):
            return found
    if any(m.get("type") == "DISTINCT_MODIFIER" for m in node.get("modifiers") or []):
        return "DISTINCT"
    match node.get("type"):
        case "SELECT_NODE":
            return _select(node, aggregates)
        case "SET_OPERATION_NODE":
            # UNION, INTERSECT and EXCEPT remove duplicate rows unless they are ALL.
            if not node.get("setop_all", True):
                return f"{node.get('setop_type', 'a set operation')} without ALL"
            # Newer DuckDB lists the parts as children, older ones as left and right.
            parts = node.get("children") or [node.get("left"), node.get("right")]
            for part in parts:
                if found := _query(part, aggregates):
                    return found
            return None
        case "RECURSIVE_CTE_NODE":
            return "a recursive CTE"
        case _:
            return None


def _select(node: dict[str, Any], aggregates: set[str]) -> str | None:
    # GROUP BY ALL leaves the groups to the binder; the parser marks it as forced.
    grouped = node.get("aggregate_handling", "STANDARD_HANDLING") != "STANDARD_HANDLING"
    if grouped or node.get("group_expressions") or any(node.get("group_sets") or []):
        return "GROUP BY"
    if node.get("having") is not None:
        return "HAVING"
    for expression in node.get("select_list", []):
        if found := _expression(expression, aggregates):
            return found
    return _table(node.get("from_table"), aggregates)


def _table(table: dict[str, Any] | None, aggregates: set[str]) -> str | None:
    if not table:
        return None
    match table.get("type"):
        case "SUBQUERY":
            return _query(table["subquery"]["node"], aggregates)
        case "JOIN":
            return _table(table.get("left"), aggregates) or _table(table.get("right"), aggregates)
        case "PIVOT":
            return "PIVOT"
        case _:
            return None


def _expression(value: Any, aggregates: set[str]) -> str | None:
    """An aggregate or window function anywhere in the expression, except inside a
    subquery: a scalar subquery yields one value, it does not merge the outer rows."""
    if isinstance(value, list):
        for item in value:
            if found := _expression(item, aggregates):
                return found
        return None
    if not isinstance(value, dict):
        return None
    match value.get("class"):
        case "SUBQUERY":
            return None
        case "WINDOW":
            return f"{value.get('function_name', 'a window function')}() OVER"
        case "FUNCTION" if str(value.get("function_name", "")).lower() in aggregates:
            return f"{value['function_name']}()"
    for item in value.values():
        if found := _expression(item, aggregates):
            return found
    return None
