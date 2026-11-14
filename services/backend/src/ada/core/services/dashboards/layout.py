"""Where a slot sits on the dashboard's grid.

A dashboard is a 12-column grid. A slot's layout is `{x, y, w, h}`: the column it starts
in (0-11), the row it starts in, and how many columns and rows it spans. Rows have no
fixed height here; the frontend decides what one row is.

Slots without a layout, and layouts with keys left out, are filled with these defaults.
"""

from collections.abc import Sequence

from ada.core.models.base import JsonObject
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Invalid

COLUMNS = 12
# Two cards side by side, each tall enough for a chart.
DEFAULT_WIDTH = 6
DEFAULT_HEIGHT = 4

KEYS = ("x", "y", "w", "h")


def default_layout(placed: Sequence[Slot]) -> JsonObject:
    """The place for a slot added after `placed`: beside the last one when a default-sized
    card still fits in its row, else at the start of a new row below everything."""
    if not placed:
        return {"x": 0, "y": 0, "w": DEFAULT_WIDTH, "h": DEFAULT_HEIGHT}
    last = placed[-1].layout
    x = last["x"] + last["w"]
    if x + DEFAULT_WIDTH <= COLUMNS:
        y = last["y"]
    else:
        x = 0
        y = max(slot.layout["y"] + slot.layout["h"] for slot in placed)
    return {"x": x, "y": y, "w": DEFAULT_WIDTH, "h": DEFAULT_HEIGHT}


def complete_layout(slot: Slot, placed: Sequence[Slot]) -> JsonObject:
    """The slot's layout with what it leaves out taken from the defaults, validated.
    `placed` holds the slots before it, whose layouts are already complete."""
    unknown = sorted(set(slot.layout) - set(KEYS))
    if unknown:
        raise Invalid(f"Slot {slot.name!r} has unknown layout keys {unknown}; use x, y, w, h")
    layout = {**default_layout(placed), **slot.layout}
    for key in KEYS:
        value = layout[key]
        # bool is an int in Python; a layout of true is not a position.
        if isinstance(value, bool) or not isinstance(value, int):
            raise Invalid(f"Slot {slot.name!r}: layout {key} must be a whole number")
    if layout["x"] < 0 or layout["y"] < 0:
        raise Invalid(f"Slot {slot.name!r}: layout x and y cannot be negative")
    if layout["w"] < 1 or layout["h"] < 1:
        raise Invalid(f"Slot {slot.name!r}: layout w and h must be at least 1")
    if layout["x"] + layout["w"] > COLUMNS:
        raise Invalid(
            f"Slot {slot.name!r} leaves the {COLUMNS}-column grid: x + w is over {COLUMNS}"
        )
    return layout
