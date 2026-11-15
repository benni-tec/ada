"""Statistic operators: named, vetted analyses with parameters (docs/spec.md, "Operator
kinds"). Each compiles to one DuckDB query over input_0, so a statistic runs, fuses and
is traced like a transform; what it adds is that the formula is the platform's, reviewed
once, not SQL an agent writes afresh. The compiled SQL is stored in the operator's
parameters, so a run replays exactly what was defined, even after this module changes.

Bounds computed here (a trend's confidence interval) are declared as measure bounds:
unlike a transform's aggregate, a statistic's interval is the right one by construction.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.errors import Invalid
from ada.core.models.schema import Column, ColumnType, GeoRole, MeasureRole, Roles
from ada.core.models.statistics import (
    CATALOGUE,
    Change,
    GapToBest,
    Outliers,
    Trend,
)
from ada.core.services.pipelines.fusion import quote

NUMERIC = frozenset({ColumnType.INTEGER, ColumnType.NUMBER})
PERIODS = NUMERIC | {ColumnType.DATE, ColumnType.TIMESTAMP}

# Two-sided 95 % critical values of Student's t by degrees of freedom. Between rows the
# smaller df's (larger) value is used, so an interval is never too narrow.
TREND_OUTPUTS = (
    "n", "first_period", "last_period", "slope", "slope_lower", "slope_upper",
    "confidence", "r2", "direction",
)  # fmt: skip

T_95 = (
    (1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571), (6, 2.447), (7, 2.365),
    (8, 2.306), (9, 2.262), (10, 2.228), (11, 2.201), (12, 2.179), (13, 2.160),
    (14, 2.145), (15, 2.131), (16, 2.120), (17, 2.110), (18, 2.101), (19, 2.093),
    (20, 2.086), (25, 2.060), (30, 2.042), (40, 2.021), (60, 2.000), (120, 1.980),
)  # fmt: skip


@dataclass(frozen=True)
class Compiled:
    sql: str
    roles: Roles


def compile_statistic(
    tool: str, arguments: JsonObject, columns: tuple[Column, ...], roles: Roles
) -> tuple[JsonObject, Compiled]:
    """The statistic's normalised arguments and its query over input_0, whose columns and
    roles are given."""
    if tool not in CATALOGUE:
        raise Invalid(f"There is no statistic {tool!r}; there are: {', '.join(CATALOGUE)}")
    model, _ = CATALOGUE[tool]
    try:
        parsed = model.model_validate(arguments)
    except ValidationError as error:
        raise Invalid(f"The arguments of {tool} are not valid: {error}") from None
    return parsed.model_dump(mode="json"), COMPILERS[tool](parsed, columns, roles)


# The statistics


def _profile(_: DomainModel, columns: tuple[Column, ...], roles: Roles) -> Compiled:
    sql = "-- statistic profile\nSELECT * FROM (SUMMARIZE SELECT * FROM input_0)"
    return Compiled(sql, Roles())


def _trend(args: DomainModel, columns: tuple[Column, ...], roles: Roles) -> Compiled:
    assert isinstance(args, Trend)
    cols = _Columns(columns)
    cols.need(args.value, NUMERIC, "value")
    cols.need(args.time, PERIODS, "time")
    cols.distinct(args.by, (args.value, args.time))
    cols.free(TREND_OUTPUTS, args.by)
    by = _list(args.by)
    x = _years(args.time, cols.type(args.time))
    partition = f"PARTITION BY {by}" if by else ""
    group = f"GROUP BY {by}" if by else ""
    keys = f"{by}, " if by else ""
    df = "(count(*) - 2)"
    sql = f"""-- statistic trend: least-squares slope of {args.value} per year, 95 % CI
WITH points AS (
  SELECT {keys}CAST({x} AS DOUBLE) AS __x, CAST({quote(args.value)} AS DOUBLE) AS __y
  FROM input_0 WHERE {quote(args.value)} IS NOT NULL AND {quote(args.time)} IS NOT NULL
), fitted AS (
  SELECT *, regr_slope(__y, __x) OVER w AS __b, regr_intercept(__y, __x) OVER w AS __a
  FROM points WINDOW w AS ({partition})
), fit AS (
  SELECT {keys}count(*) AS n, min(__x) AS first_period, max(__x) AS last_period,
    any_value(__b) AS slope, regr_r2(__y, __x) AS r2,
    sqrt(sum(power(__y - (__a + __b * __x), 2)) / nullif({df}, 0)
      / nullif(regr_sxx(__y, __x), 0)) AS __se,
    {_t95(df)} AS __t
  FROM fitted {group}
)
SELECT {keys}n, first_period, last_period, slope,
  slope - __t * __se AS slope_lower, slope + __t * __se AS slope_upper, 95 AS confidence, r2,
  CASE WHEN n < 3 OR __se IS NULL THEN 'too few points'
    WHEN slope - __t * __se > 0 THEN 'rising' WHEN slope + __t * __se < 0 THEN 'falling'
    ELSE 'no clear trend' END AS direction
FROM fit"""
    measure = MeasureRole(value="slope", lower="slope_lower", upper="slope_upper")
    return Compiled(sql, Roles(geo=_kept_geo(roles, args.by), measures=(measure,)))


def _change(args: DomainModel, columns: tuple[Column, ...], roles: Roles) -> Compiled:
    assert isinstance(args, Change)
    cols = _Columns(columns)
    cols.need(args.value, NUMERIC, "value")
    cols.need(args.time, PERIODS, "time")
    cols.distinct(args.by, (args.value, args.time))
    cols.free(("previous_period", "previous_value", "change", "change_pct"))
    window = _window(args.by, f"ORDER BY {quote(args.time)}")
    value, k = quote(args.value), args.periods
    sql = f"""-- statistic change: {args.value} against {k} period(s) earlier
SELECT *, change / nullif(abs(previous_value), 0) * 100 AS change_pct FROM (
  SELECT *, lag({quote(args.time)}, {k}) OVER w AS previous_period,
    lag({value}, {k}) OVER w AS previous_value,
    {value} - lag({value}, {k}) OVER w AS change
  FROM input_0 WINDOW w AS ({window})
)"""
    return Compiled(sql, _plus(roles, "change"))


def _gap_to_best(args: DomainModel, columns: tuple[Column, ...], roles: Roles) -> Compiled:
    assert isinstance(args, GapToBest)
    cols = _Columns(columns)
    cols.need(args.value, NUMERIC, "value")
    cols.need(args.entity, None, "entity")
    cols.distinct(args.within, (args.value, args.entity))
    cols.free(("best_value", "best_entity", "gap", "gap_pct", "rank"))
    value, entity = quote(args.value), quote(args.entity)
    best, pick = ("max", "arg_max") if args.better == "higher" else ("min", "arg_min")
    gap = "best_value - __v" if args.better == "higher" else "__v - best_value"
    order = "DESC" if args.better == "higher" else "ASC"
    window = _window(args.within, "")
    sql = f"""-- statistic gap_to_best: shortfall of {args.value} against the best {args.entity}, {args.better} is better
SELECT * EXCLUDE (__v), {gap} AS gap, ({gap}) / nullif(abs(best_value), 0) * 100 AS gap_pct FROM (
  SELECT *, {value} AS __v, {best}({value}) OVER w AS best_value,
    {pick}({entity}, {value}) OVER w AS best_entity,
    rank() OVER ({_window(args.within, f"ORDER BY {value} {order} NULLS LAST")}) AS rank
  FROM input_0 WINDOW w AS ({window})
)"""  # noqa: E501
    return Compiled(sql, _plus(roles, "gap"))


def _outliers(args: DomainModel, columns: tuple[Column, ...], roles: Roles) -> Compiled:
    assert isinstance(args, Outliers)
    cols = _Columns(columns)
    cols.need(args.value, NUMERIC, "value")
    cols.distinct(args.within, (args.value,))
    cols.free(("median", "mad", "robust_z", "is_outlier"))
    value = f"CAST({quote(args.value)} AS DOUBLE)"
    window = _window(args.within, "")
    sql = f"""-- statistic outliers: robust z-score of {args.value} (median, MAD; mean absolute deviation when MAD is 0), flagged above {args.threshold:g}
SELECT *, coalesce(abs(robust_z) > {args.threshold!r}, false) AS is_outlier FROM (
  SELECT * EXCLUDE (__v, __meanad), CASE
      WHEN mad > 0 THEN 0.6745 * (__v - median) / mad
      WHEN __meanad > 0 THEN (__v - median) / (1.253314 * __meanad)
      WHEN __v IS NOT NULL THEN 0.0 END AS robust_z FROM (
    SELECT *, avg(abs(__v - median)) OVER w AS __meanad FROM (
      SELECT *, {value} AS __v, median({value}) OVER w AS median, mad({value}) OVER w AS mad
      FROM input_0 WINDOW w AS ({window})
    ) WINDOW w AS ({window})
  )
)"""  # noqa: E501
    return Compiled(sql, _plus(roles, "robust_z"))


# Each statistic's query, by name; its arguments and summary are in the catalogue.
COMPILERS: dict[str, Callable[[DomainModel, tuple[Column, ...], Roles], Compiled]] = {
    "profile": _profile,
    "trend": _trend,
    "change": _change,
    "gap_to_best": _gap_to_best,
    "outliers": _outliers,
}


# Helpers


class _Columns:
    def __init__(self, columns: tuple[Column, ...]) -> None:
        self.by_name = {column.name: column for column in columns}
        # DuckDB resolves names case-insensitively, so a clash is one too.
        self.folded = {column.name.lower() for column in columns}

    def type(self, name: str) -> ColumnType:
        return self.by_name[name].type

    def need(self, name: str, types: frozenset[ColumnType] | None, what: str) -> None:
        column = self.by_name.get(name)
        if column is None:
            known = ", ".join(self.by_name) or "none"
            raise Invalid(f"The {what} column {name!r} is not a column of the input ({known})")
        if types is not None and column.type not in types:
            allowed = " or ".join(sorted(types))
            raise Invalid(f"The {what} column {name!r} must be {allowed}, not {column.type}")

    def distinct(self, group: Sequence[str], used: Sequence[str]) -> None:
        for name in group:
            self.need(name, None, "grouping")
        if len(set(group)) != len(group) or set(group) & set(used):
            raise Invalid("Each grouping column may appear once and not be the value or time")

    def free(self, names: Sequence[str], among: Sequence[str] | None = None) -> None:
        """The names this statistic adds must not clash with the input's columns (or, when
        given, with the ones it keeps)."""
        kept = self.folded if among is None else {name.lower() for name in among}
        taken = [name for name in names if name.lower() in kept]
        if taken or any(name.startswith("__") for name in kept):
            raise Invalid(
                f"The input already has the column(s) {', '.join(taken) or 'starting with __'}"
                ", which this statistic uses; rename them in a transform first"
            )


def _list(names: Sequence[str]) -> str:
    return ", ".join(quote(name) for name in names)


def _window(group: Sequence[str], order: str) -> str:
    partition = f"PARTITION BY {_list(group)}" if group else ""
    return " ".join(part for part in (partition, order) if part)


def _years(name: str, type: ColumnType) -> str:
    column = quote(name)
    if type in NUMERIC:
        return column
    return f"(year({column}) + (dayofyear({column}) - 1) / 365.25)"


def _t95(df: str) -> str:
    cases = " ".join(
        f"WHEN {df} < {nxt} THEN {t}" for (_, t), (nxt, _) in zip(T_95, T_95[1:], strict=False)
    )
    return f"CASE WHEN {df} < 1 THEN NULL {cases} ELSE {T_95[-1][1]} END"


def _kept_geo(roles: Roles, by: Sequence[str]) -> GeoRole | None:
    return roles.geo if roles.geo is not None and roles.geo.code in by else None


def _plus(roles: Roles, measure: str) -> Roles:
    """The input's roles, which every row keeps, with one more measure."""
    return roles.model_copy(update={"measures": (*roles.measures, MeasureRole(value=measure))})
