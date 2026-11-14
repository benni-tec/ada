"""Shaping a source's answer into a plain table before it is stored."""

import json
from typing import Any

import pytest

from ada.core.models.analysis import FetchedData
from ada.core.models.errors import Invalid
from ada.core.models.sources import DataFormat
from ada.core.services.sources.shaping import shape, shape_options
from factories import NOW


def fetched(content: bytes, format: DataFormat = DataFormat.JSON) -> FetchedData:
    return FetchedData(content=content, format=format, fetched_at=NOW, origin="https://x.test")


def shaped_json(document: Any, **options: Any) -> list[dict[str, Any]]:
    return json.loads(shape(fetched(json.dumps(document).encode()), options).content)


def shaped_csv(content: bytes, **csv: Any) -> str:
    return shape(fetched(content, DataFormat.CSV), {"csv": csv}).content.decode()


def test_json_rows_are_found_by_their_path() -> None:
    document = {"result": {"pages": [{"items": [{"a": 1}, {"a": 2}]}]}}

    assert shaped_json(document, rows="result.pages.0.items") == [{"a": 1}, {"a": 2}]


def test_nested_objects_are_flattened() -> None:
    document = [{"label": "Finland", "survival": {"value": "17.9", "ci": {"low": "16"}}}]

    assert shaped_json(document) == [
        {"label": "Finland", "survival_value": "17.9", "survival_ci_low": "16"}
    ]


def test_every_record_gets_every_column_in_one_order() -> None:
    assert shaped_json([{"a": 1}, {"b": 2, "a": 3}]) == [
        {"a": 1, "b": None},
        {"a": 3, "b": 2},
    ]


def test_a_single_object_is_one_record() -> None:
    assert shaped_json({"a": 1}) == [{"a": 1}]


def test_fields_pick_rename_and_convert() -> None:
    document = {"dataset": [{"label": "Finland", "year": 2022.0, "survival": {"value": "17.9"}}]}
    fields = {
        "country": "label",
        "year": {"path": "year", "type": "integer"},
        "survival": {"path": "survival.value", "type": "number"},
        "missing": "survival.lowCI",
    }

    assert shaped_json(document, rows="dataset", fields=fields) == [
        {"country": "Finland", "year": 2022, "survival": 17.9, "missing": None}
    ]


@pytest.mark.parametrize(
    ("type", "value", "expected"),
    [
        ("integer", "12", 12),
        ("number", "1.5", 1.5),
        ("text", 3, "3"),
        ("boolean", "true", True),
        ("boolean", 0, False),
        ("number", "", None),
    ],
)
def test_field_types(type: str, value: Any, expected: Any) -> None:
    fields = {"v": {"path": "v", "type": type}}

    assert shaped_json([{"v": value}], fields=fields) == [{"v": expected}]


@pytest.mark.parametrize(
    ("document", "options"),
    [
        ({"data": []}, {"rows": "dataset"}),
        ({"data": 3}, {"rows": "data"}),
        ([1, 2], {}),
        ([{"v": "n/a"}], {"fields": {"v": {"path": "v", "type": "number"}}}),
        ([{"v": "1.5"}], {"fields": {"v": {"path": "v", "type": "integer"}}}),
    ],
)
def test_json_of_another_shape_is_invalid(document: Any, options: dict[str, Any]) -> None:
    with pytest.raises(Invalid):
        shaped_json(document, **options)


def test_content_that_is_not_json_is_invalid() -> None:
    with pytest.raises(Invalid, match="JSON"):
        shape(fetched(b"<html>"), {})


def test_csv_without_options_is_kept_as_it_came() -> None:
    data = fetched(b"a;b\r\n1;2\r\n", DataFormat.CSV)

    assert shape(data, {}) == data


def test_csv_is_rewritten_as_utf8_with_commas() -> None:
    content = "﻿region;value\r\nÅland;..\r\nHelsinki;74,3\r\n".encode()

    assert shaped_csv(content, delimiter=";", null_values=[".."]) == (
        'region,value\nÅland,\nHelsinki,"74,3"\n'
    )


def test_csv_options_skip_rows_and_rename_columns() -> None:
    content = "Title line\n\nRegion name,Value 2024\nÅland,1\n".encode("latin-1")

    assert shaped_csv(content, encoding="latin-1", skip_rows=2, columns=["region", "value"]) == (
        "region,value\nÅland,1\n"
    )


@pytest.mark.parametrize(
    ("content", "csv"),
    [
        (b"a,b\n1,2\n", {"columns": ["only"]}),
        (b"a,b\n1,2,3\n", {}),
        (b"", {}),
        (b"\xff\xfe", {"encoding": "utf-8"}),
    ],
)
def test_csv_of_another_shape_is_invalid(content: bytes, csv: dict[str, Any]) -> None:
    with pytest.raises(Invalid):
        shaped_csv(content, **csv)


def test_parquet_is_kept_as_it_came() -> None:
    data = fetched(b"PAR1", DataFormat.PARQUET)

    assert shape(data, {"rows": "x"}) == data


def test_options_of_the_readers_are_ignored() -> None:
    options = shape_options({"method": "POST", "body": {"query": []}, "rows": "data"})

    assert options.rows == "data"
