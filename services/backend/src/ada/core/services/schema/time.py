"""Periods as intervals: reading a source's native period, splitting a time range into the
periods of a grain, and naming a period to a source or a snapshot.

A period is an Interval with both ends inclusive. Sources write periods their own way:

    2024, "2024"          the year 2024
    "2020-2024"           one window of five years (also with an en dash or a slash)
    "2024Q1"              the first quarter of 2024
    "2024M03", "2024-03"  March 2024
    "2024-03-15"          that day, or the period of the grain that contains it

A time range selects every period it overlaps: a row is in the range when its period and
the range share at least one day. Periods are atomic, so a range that starts in June
still takes the whole year.
"""

import calendar
import re
from datetime import date

from ada.core.models.time import Grain, Interval, TimeRange

_YEAR = re.compile(r"(\d{4})")
_WINDOW = re.compile(r"(\d{4})\s*[-–—/]\s*(\d{4})")
_QUARTER = re.compile(r"(\d{4})\s*-?\s*Q([1-4])", re.IGNORECASE)
_MONTH = re.compile(r"(\d{4})\s*(?:M|-)(\d{2})", re.IGNORECASE)
_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?")

# How a period is written in a request when the source's options do not say: the
# conventions of PxWeb, which Sotkanet shares for years.
DEFAULT_FORMATS = {
    Grain.YEAR: "{year}",
    Grain.QUARTER: "{year}Q{quarter}",
    Grain.MONTH: "{year}M{month:02d}",
}


def parse_period(value: object, grain: Grain | None = None) -> Interval | None:
    """The period a source's value names; None for an empty value. A single day is the
    period of `grain` that contains it, or just that day without a grain. Raises
    ValueError for anything else."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{value!r} is not a period")
    if isinstance(value, date):
        return containing(value, grain) if grain else Interval(start=value, end=value)
    if isinstance(value, int | float):
        if not float(value).is_integer():
            raise ValueError(f"{value!r} is not a year")
        return year(int(value))
    text = str(value).strip()
    if match := _YEAR.fullmatch(text):
        return year(int(match[1]))
    if match := _WINDOW.fullmatch(text):
        first, last = int(match[1]), int(match[2])
        if last < first:
            raise ValueError(f"{text!r} ends before it starts")
        return Interval(start=date(first, 1, 1), end=date(last, 12, 31))
    if match := _QUARTER.fullmatch(text):
        return quarter(int(match[1]), int(match[2]))
    if match := _MONTH.fullmatch(text):
        return month(int(match[1]), int(match[2]))
    if match := _DAY.fullmatch(text):
        day = date.fromisoformat(match[1])
        return containing(day, grain) if grain else Interval(start=day, end=day)
    raise ValueError(f"{text!r} is not a period: expected e.g. 2024, 2020-2024, 2024Q1, 2024M03")


def year(number: int) -> Interval:
    return Interval(start=date(number, 1, 1), end=date(number, 12, 31))


def quarter(number: int, which: int) -> Interval:
    if not 1 <= which <= 4:
        raise ValueError(f"There is no quarter {which}")
    first = 3 * which - 2
    return Interval(start=date(number, first, 1), end=_month_end(number, first + 2))


def month(number: int, which: int) -> Interval:
    if not 1 <= which <= 12:
        raise ValueError(f"There is no month {which}")
    return Interval(start=date(number, which, 1), end=_month_end(number, which))


def containing(day: date, grain: Grain) -> Interval:
    """The period of the grain that the day falls in."""
    match grain:
        case Grain.YEAR:
            return year(day.year)
        case Grain.QUARTER:
            return quarter(day.year, (day.month - 1) // 3 + 1)
        case Grain.MONTH:
            return month(day.year, day.month)


def following(period: Interval, grain: Grain) -> Interval:
    """The period of the grain right after this one."""
    after = period.end.toordinal() + 1
    return containing(date.fromordinal(after), grain)


def periods(time_range: TimeRange, grain: Grain, today: date) -> tuple[Interval, ...]:
    """Every period of the grain that the range overlaps, oldest first. An open end runs
    to the period that contains today. The range needs a start: nothing says where an
    open start would begin."""
    if time_range.start is None:
        raise ValueError("A range without a start cannot be split into periods")
    end = time_range.end or today
    found: list[Interval] = []
    period = containing(time_range.start, grain)
    while period.start <= end:
        found.append(period)
        period = following(period, grain)
    return tuple(found)


def overlaps(period: Interval, time_range: TimeRange) -> bool:
    """Whether the period is in the range: they share at least one day."""
    if time_range.start is not None and period.end < time_range.start:
        return False
    return time_range.end is None or period.start <= time_range.end


def is_bounded(time_range: TimeRange) -> bool:
    """Whether the range asks for less than everything."""
    return time_range.start is not None or time_range.end is not None


def check_range(time_range: TimeRange) -> None:
    """Raises ValueError for a range that ends before it starts."""
    if time_range.start and time_range.end and time_range.end < time_range.start:
        raise ValueError(
            f"The time range ends ({time_range.end}) before it starts ({time_range.start})"
        )


def label(period: Interval, grain: Grain, format: str | None = None) -> str:
    """How a period is written in a request to a source, e.g. "2024" or "2024Q1". The
    format may use {year}, {quarter} and {month}."""
    template = format or DEFAULT_FORMATS[grain]
    start = period.start
    return template.format(year=start.year, quarter=(start.month - 1) // 3 + 1, month=start.month)


def period_key(period: Interval) -> str:
    """The parameters key of the snapshot that holds one period of a source."""
    return f"period:{period.start.isoformat()}/{period.end.isoformat()}"


def _month_end(number: int, which: int) -> date:
    return date(number, which, calendar.monthrange(number, which)[1])
