"""The component tree of reports and templates, and the version arithmetic."""

import re
from datetime import date
from uuid import uuid7

import pytest

from ada.core.models.errors import Invalid
from ada.core.models.reports import VersionBump
from ada.core.models.time import TimeRange
from ada.core.services.reports import content as tree
from ada.core.services.reports.versions import State, bumped, decide, parse_version, required


def parse(*blocks: object, kind: tree.Tree = tree.Tree.REPORT) -> list[object]:
    return tree.dump(tree.parse({"blocks": list(blocks)}, kind))


def test_a_tree_is_stored_with_its_defaults_filled_in() -> None:
    widget_id = uuid7()
    stored = parse(
        {"type": "heading", "text": "Screening gap"},
        {"type": "section", "blocks": [{"type": "text", "text": "Why."}]},
        {"type": "callout", "text": "Below target"},
        {"type": "widget", "widget_id": str(widget_id)},
    )
    assert stored == [
        {"type": "heading", "text": "Screening gap", "level": 2},
        {"type": "section", "title": "", "blocks": [{"type": "text", "text": "Why."}]},
        {"type": "callout", "tone": "note", "title": "", "text": "Below target"},
        {"type": "widget", "widget_id": str(widget_id), "caption": ""},
    ]


def test_widgets_are_listed_once_in_reading_order() -> None:
    first, second = uuid7(), uuid7()
    blocks = tree.parse(
        {
            "blocks": [
                {"type": "widget", "widget_id": str(second)},
                {"type": "section", "blocks": [{"type": "widget", "widget_id": str(first)}]},
                {"type": "widget", "widget_id": str(second)},
            ]
        },
        tree.Tree.REPORT,
    )
    assert tree.widget_ids(blocks) == [second, first]


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"type": "chart", "data": [1, 2]}, "blocks[0]: unknown component 'chart'"),
        ({"text": "no type"}, "blocks[0]: a block needs a `type`"),
        # Data on a static block: only widgets show data.
        ({"type": "text", "text": "x", "rows": [[1]]}, "blocks[0].rows: not a field"),
        ({"type": "callout", "text": "x", "value": 81.5}, "blocks[0].value: not a field"),
        ({"type": "heading", "text": "x", "widget_id": str(uuid7())}, "blocks[0].widget_id"),
        ({"type": "widget", "widget_id": str(uuid7()), "rows": []}, "blocks[0].rows"),
        ({"type": "text", "text": ""}, "blocks[0].text"),
        ({"type": "heading", "text": "x", "level": 4}, "blocks[0].level"),
        ({"type": "widget"}, "a widget block needs a `widget_id`"),
        ({"type": "widget", "slot": "gap"}, "names a `widget_id`, not a `slot`"),
        ({"type": "widget", "widget_id": "not-an-id"}, "blocks[0].widget_id"),
    ],
)
def test_a_wrong_block_is_invalid_and_located(block: object, message: str) -> None:
    with pytest.raises(Invalid, match=_escaped(message)):
        parse(block)


def test_a_nested_problem_names_its_path() -> None:
    with pytest.raises(Invalid, match=_escaped("blocks[1].blocks[0].text")):
        parse(
            {"type": "text", "text": "fine"},
            {"type": "section", "blocks": [{"type": "text", "text": 5}]},
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({}, "needs a `blocks` list"),
        ({"blocks": "text"}, "blocks"),
        ({"blocks": [], "title": "x"}, "unknown keys ['title']"),
        ({"blocks": [], "sources": []}, "`sources` is generated"),
        ([], "must be an object"),
    ],
)
def test_the_document_itself_is_checked(content: object, message: str) -> None:
    with pytest.raises(Invalid, match=_escaped(message)):
        tree.parse(content, tree.Tree.REPORT)  # type: ignore[arg-type]


def test_sections_nest_only_so_deep() -> None:
    block: dict[str, object] = {"type": "text", "text": "deep"}
    for _ in range(tree.MAX_DEPTH):
        block = {"type": "section", "blocks": [block]}
    with pytest.raises(Invalid, match="nest at most"):
        parse(block)


def test_a_template_places_slots_not_widgets() -> None:
    assert parse({"type": "widget", "slot": "gap"}, kind=tree.Tree.TEMPLATE) == [
        {"type": "widget", "slot": "gap", "caption": ""}
    ]
    with pytest.raises(Invalid, match="names a `slot`"):
        parse({"type": "widget", "widget_id": str(uuid7())}, kind=tree.Tree.TEMPLATE)
    with pytest.raises(Invalid, match="more than once"):
        parse(
            {"type": "widget", "slot": "gap"},
            {"type": "widget", "slot": "gap"},
            kind=tree.Tree.TEMPLATE,
        )


def test_filling_a_template_replaces_its_slots() -> None:
    widget_id = uuid7()
    blocks = tree.parse(
        {
            "blocks": [
                {"type": "section", "title": "Gap", "blocks": [{"type": "widget", "slot": "g"}]}
            ]
        },
        tree.Tree.TEMPLATE,
    )
    filled = tree.fill(blocks, {"g": widget_id})
    assert tree.widget_ids(filled) == [widget_id]
    assert tree.slot_names(filled) == []


# Versions


def test_versions_count_up_by_level() -> None:
    assert bumped("1.2.3", VersionBump.MAJOR) == "2.0.0"
    assert bumped("1.2.3", VersionBump.MINOR) == "1.3.0"
    assert bumped("1.2.3", VersionBump.PATCH) == "1.2.4"
    assert parse_version("1.10.0") > parse_version("1.9.0")
    with pytest.raises(Invalid):
        parse_version("1.0")


def state(**changes: object) -> State:
    base: dict[str, object] = {
        "operators": frozenset({"op_a"}),
        "run_id": RUN,
        "time_range": TimeRange(),
        "blocks": [{"type": "text", "text": "a"}],
    }
    return State(**(base | changes))  # type: ignore[arg-type]


RUN = uuid7()


def test_the_required_level_follows_from_what_changed() -> None:
    assert required(state(), state()) is None
    assert required(state(), state(blocks=[{"type": "text", "text": "b"}])) is VersionBump.PATCH
    assert required(state(), state(run_id=uuid7())) is VersionBump.MINOR
    assert (
        required(state(), state(time_range=TimeRange(start=date(2024, 1, 1)))) is VersionBump.MINOR
    )
    assert required(state(), state(operators=frozenset({"op_b"}))) is VersionBump.MAJOR
    # The pipelines outrank the run: a new run with new widgets is still major.
    assert required(state(), state(operators=frozenset(), run_id=uuid7())) is VersionBump.MAJOR


def test_a_given_level_may_be_higher_but_never_lower() -> None:
    assert decide("1.0.0", VersionBump.PATCH, None) == "1.0.1"
    assert decide("1.0.0", VersionBump.PATCH, VersionBump.MAJOR) == "2.0.0"
    with pytest.raises(Invalid, match="too small"):
        decide("1.0.0", VersionBump.MINOR, VersionBump.PATCH)


def _escaped(message: str) -> str:
    return re.escape(message)
