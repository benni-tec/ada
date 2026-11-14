"""Periods as intervals: reading a source's native period, splitting a range into periods,
and the `period` shaping option that turns a year or a window into a time role's columns."""

import csv
import io
import json
from datetime import UTC, date, datetime

import pytest

from ada.core.models.analysis import FetchedData
from ada.core.models.errors import Invalid
from ada.core.models.schema import TimeRole
from ada.core.models.sources import DataFormat
from ada.core.models.time import Grain, Interval, TimeRange
from ada.core.services.schema.time import (
    check_range,
    label,
    overlaps,
    parse_period,
    period_key,
    periods,
)
from ada.core.services.sources.shaping import shape, shape_options, split_periods


def span(start: str, end: str) -> Interval:
    return Interval(start=date.fromisoformat(start), end=date.fromisoformat(end))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2024, span("2024-01-01", "2024-12-31")),
        (2024.0, span("2024-01-01", "2024-12-31")),
        ("2024", span("2024-01-01", "2024-12-31")),
        # A multi-year window is one period, however it is written.
        ("2020-2024", span("2020-01-01", "2024-12-31")),
        ("2022–2024", span("2022-01-01", "2024-12-31")),
        ("2015 / 2019", span("2015-01-01", "2019-12-31")),
        ("2024Q1", span("2024-01-01", "2024-03-31")),
        ("2024Q4", span("2024-10-01", "2024-12-31")),
        ("2024M02", span("2024-02-01", "2024-02-29")),
        ("2023-02", span("2023-02-01", "2023-02-28")),
        ("2024-03-15", span("2024-03-15", "2024-03-15")),
        (date(2024, 3, 15), span("2024-03-15", "2024-03-15")),
    ],
)
def test_a_source_s_period_is_read_as_an_interval(value: object, expected: Interval) -> None:
    assert parse_period(value) == expected


def test_a_grain_widens_a_day_to_its_period() -> None:
    assert parse_period("2024-05-17", Grain.QUARTER) == span("2024-04-01", "2024-06-30")
    assert parse_period("2024-05-17", Grain.MONTH) == span("2024-05-01", "2024-05-31")
    assert parse_period("2024-05-17T10:00:00", Grain.YEAR) == span("2024-01-01", "2024-12-31")


@pytest.mark.parametrize("value", [None, ""])
def test_an_empty_value_has_no_period(value: object) -> None:
    assert parse_period(value) is None


@pytest.mark.parametrize("value", ["soon", "2024-2020", "2024Q5", "2024M13", 2024.5, True])
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(ValueError):
        parse_period(value)


def test_a_range_splits_into_every_period_it_overlaps() -> None:
    years = periods(TimeRange(start=date(2022, 6, 1), end=date(2024, 2, 1)), Grain.YEAR, date.max)
    assert years == (
        span("2022-01-01", "2022-12-31"),
        span("2023-01-01", "2023-12-31"),
        span("2024-01-01", "2024-12-31"),
    )
    quarters = periods(
        TimeRange(start=date(2023, 11, 1), end=date(2024, 4, 1)), Grain.QUARTER, date.max
    )
    assert [label(q, Grain.QUARTER) for q in quarters] == ["2023Q4", "2024Q1", "2024Q2"]
    months = periods(
        TimeRange(start=date(2023, 12, 5), end=date(2024, 1, 5)), Grain.MONTH, date.max
    )
    assert [label(m, Grain.MONTH) for m in months] == ["2023M12", "2024M01"]


def test_an_open_end_runs_to_today_and_an_open_start_cannot_be_split() -> None:
    today = date(2026, 11, 14)
    assert periods(TimeRange(start=date(2025, 1, 1)), Grain.YEAR, today) == (
        span("2025-01-01", "2025-12-31"),
        span("2026-01-01", "2026-12-31"),
    )
    with pytest.raises(ValueError):
        periods(TimeRange(end=date(2025, 1, 1)), Grain.YEAR, today)


def test_a_period_is_in_a_range_when_they_share_a_day() -> None:
    window = span("2020-01-01", "2024-12-31")
    assert overlaps(window, TimeRange(start=date(2024, 1, 1), end=date(2024, 12, 31)))
    assert overlaps(window, TimeRange(end=date(2020, 1, 1)))
    assert not overlaps(window, TimeRange(start=date(2025, 1, 1)))
    assert overlaps(window, TimeRange())


def test_labels_keys_and_ranges() -> None:
    year = span("2024-01-01", "2024-12-31")
    assert label(year, Grain.YEAR) == "2024"
    assert label(year, Grain.YEAR, "FY{year}") == "FY2024"
    assert period_key(year) == "period:2024-01-01/2024-12-31"
    with pytest.raises(ValueError, match="ends"):
        check_range(TimeRange(start=date(2024, 1, 1), end=date(2023, 1, 1)))


def fetched(content: bytes, format: DataFormat = DataFormat.JSON) -> FetchedData:
    return FetchedData(
        content=content, format=format, fetched_at=datetime(2026, 1, 1, tzinfo=UTC), origin="x"
    )


def test_the_period_option_adds_the_time_role_s_columns_to_json() -> None:
    data = fetched(
        json.dumps([{"year": 2023, "v": 1}, {"year": "2024", "v": 2}, {"v": 3}]).encode()
    )

    shaped = shape(data, {"period": {"column": "year"}})

    assert json.loads(shaped.content) == [
        {"year": 2023, "v": 1, "period_start": "2023-01-01", "period_end": "2023-12-31"},
        {"year": "2024", "v": 2, "period_start": "2024-01-01", "period_end": "2024-12-31"},
        # No value, no period: the row is in no bounded range.
        {"year": None, "v": 3, "period_start": None, "period_end": None},
    ]


def test_the_period_option_reads_windows_after_the_fields() -> None:
    data = fetched(json.dumps({"data": [{"p": "2020-2024", "x": {"v": "1.5"}}]}).encode())
    options = {
        "rows": "data",
        "fields": {"window": "p", "value": {"path": "x.v", "type": "number"}},
        "period": {"column": "window", "start": "first_day", "end": "last_day"},
    }

    shaped = shape(data, options)

    assert json.loads(shaped.content) == [
        {"window": "2020-2024", "value": 1.5, "first_day": "2020-01-01", "last_day": "2024-12-31"}
    ]


def test_the_period_option_works_on_csv_too() -> None:
    data = fetched(b"\xef\xbb\xbfquarter;n\n2024Q1;5\n2024Q2;..\n", DataFormat.CSV)
    options = {
        "csv": {"delimiter": ";", "null_values": [".."]},
        "period": {"column": "quarter"},
    }

    shaped = shape(data, options)

    assert list(csv.reader(io.StringIO(shaped.content.decode()))) == [
        ["quarter", "n", "period_start", "period_end"],
        ["2024Q1", "5", "2024-01-01", "2024-03-31"],
        ["2024Q2", "", "2024-04-01", "2024-06-30"],
    ]
    # Without `csv` the period option still parses the CSV, with its defaults.
    plain = shape(fetched(b"year,n\n2024,5\n", DataFormat.CSV), {"period": {"column": "year"}})
    assert plain.content == b"year,n,period_start,period_end\n2024,5,2024-01-01,2024-12-31\n"


def test_an_unreadable_period_names_its_column() -> None:
    data = fetched(json.dumps([{"year": "last year"}]).encode())
    with pytest.raises(Invalid, match="Column year"):
        shape(data, {"period": {"column": "year"}})
    with pytest.raises(Invalid, match="not a column"):
        shape(fetched(b"a\n1\n", DataFormat.CSV), {"period": {"column": "year"}})


def test_period_options_are_checked_at_registration() -> None:
    with pytest.raises(Invalid, match="different columns"):
        shape_options({"period": {"column": "year", "start": "p", "end": "p"}})
    with pytest.raises(Invalid):
        shape_options({"period": {"column": "year", "grain": "decade"}})


def test_a_json_field_keeps_a_nested_value_as_its_text() -> None:
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    data = fetched(json.dumps([{"properties": {"code": "01"}, "geometry": geometry}]).encode())
    options = {"fields": {"code": "properties.code", "shape": {"path": "geometry", "type": "json"}}}

    [row] = json.loads(shape(data, options).content)

    assert row["code"] == "01"
    assert json.loads(row["shape"]) == geometry


ROLE = TimeRole(start="period_start", end="period_end", grain=Grain.YEAR)
Y2023, Y2024 = span("2023-01-01", "2023-12-31"), span("2024-01-01", "2024-12-31")


def test_an_answer_for_several_periods_is_split_by_period() -> None:
    rows = [
        {"v": 1, "period_start": "2023-01-01", "period_end": "2023-12-31"},
        {"v": 2, "period_start": "2024-01-01", "period_end": "2024-12-31"},
        {"v": 3, "period_start": "2023-01-01", "period_end": "2023-12-31"},
    ]
    parts = split_periods(fetched(json.dumps(rows).encode()), ROLE, [Y2023, Y2024])

    assert {p: [r["v"] for r in json.loads(d.content)] for p, d in parts.items()} == {
        Y2023: [1, 3],
        Y2024: [2],
    }
    table = b"v,period_start,period_end\n1,2024-01-01,2024-12-31\n"
    [(period, part)] = split_periods(fetched(table, DataFormat.CSV), ROLE, [Y2023, Y2024]).items()
    assert (period, part.content) == (Y2024, table)


def test_a_period_nobody_asked_for_is_refused() -> None:
    rows = [{"v": 1, "period_start": "2022-01-01", "period_end": "2022-12-31"}]
    with pytest.raises(Invalid, match="not asked"):
        split_periods(fetched(json.dumps(rows).encode()), ROLE, [Y2023])
    with pytest.raises(Invalid, match="no period"):
        split_periods(fetched(b'[{"v": 1}]'), ROLE, [Y2023])
