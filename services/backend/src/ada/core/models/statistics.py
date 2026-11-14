"""The statistics a statistic operator can run (docs/spec.md, "Operator kinds"): each
one's arguments and what it computes. The queries are the pipeline service's
(core/services/pipelines/statistics.py)."""

from typing import Literal

from pydantic import Field

from ada.core.models.base import DomainModel


class Profile(DomainModel):
    pass


class Trend(DomainModel):
    value: str
    # The period: a year as a number, or a date (converted to fractional years).
    time: str
    # One trend per combination of these columns; none for one trend overall.
    by: tuple[str, ...] = ()


class Change(DomainModel):
    value: str
    time: str
    by: tuple[str, ...] = ()
    # Compare with the value this many periods earlier.
    periods: int = Field(default=1, ge=1, le=100)


class GapToBest(DomainModel):
    value: str
    # What is compared, e.g. the region or country column.
    entity: str
    # Compared within each combination of these, e.g. the year and sex.
    within: tuple[str, ...] = ()
    better: Literal["higher", "lower"] = "higher"


class Outliers(DomainModel):
    value: str
    within: tuple[str, ...] = ()
    # Robust z-score (median and MAD) above which a value is flagged.
    threshold: float = Field(default=3.5, gt=0, le=100)


# Each statistic's arguments and what it returns.
CATALOGUE: dict[str, tuple[type[DomainModel], str]] = {
    "profile": (
        Profile,
        "one row per column of the input: type, min, max, distinct values, mean, "
        "quartiles, count and share of nulls (DuckDB SUMMARIZE). For checking data "
        "quality before analysing.",
    ),
    "trend": (
        Trend,
        "the least-squares slope of `value` per year over `time`, per group of `by`, "
        "with its 95 % confidence interval (Student's t; `confidence` is 95), r2, "
        "the number of points, "
        "the first and last period and a direction (rising, falling, no clear trend, "
        "too few points).",
    ),
    "change": (
        Change,
        "every row with the value `periods` periods earlier in its `by` group "
        "(previous_period, previous_value), the change and change_pct.",
    ),
    "gap_to_best": (
        GapToBest,
        "every row with the best `value` among the `entity` rows of its `within` group "
        "(best_value, best_entity), its shortfall against it (gap, gap_pct; 0 for the "
        "best) and its rank; `better` says whether higher or lower is better.",
    ),
    "outliers": (
        Outliers,
        "every row with the median and median absolute deviation of `value` in its "
        "`within` group, the robust z-score and is_outlier (|z| above `threshold`).",
    ),
}


def described() -> str:
    """Every statistic with its arguments, for a tool's description."""
    return "\n".join(
        f"- {name} ({', '.join(arguments.model_fields) or 'none'}): {summary}"
        for name, (arguments, summary) in CATALOGUE.items()
    )
