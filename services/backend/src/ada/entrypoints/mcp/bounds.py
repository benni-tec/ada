"""Lossy previews for models only; stored data and HTTP results stay intact."""

import json
from typing import Any

from ada.core.models.base import DomainModel
from ada.core.models.errors import Invalid

MAX_CELL_CHARS = 300
MAX_RESULT_BYTES = 20_000


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"…[+{len(value) - MAX_CELL_CHARS} chars]"
    if isinstance(value, (list, tuple)):
        return [_clip(cell) for cell in value]
    if isinstance(value, dict):
        return {key: _clip(cell) for key, cell in value.items()}
    return value


def bound_rows[T: DomainModel](answer: T, *, nested: bool = False) -> T:
    """Bound the complete JSON envelope, including metadata and truncation notices."""
    data = answer.model_dump(mode="json")
    table = data["rows"] if nested else data
    original = table["rows"]
    clipped = _clip(original)

    def fits(kept: int) -> bool:
        table["rows"] = clipped[:kept]
        table["dropped_rows"] = len(clipped) - kept
        # Count escaped Unicode and pretty-print whitespace too, conservatively covering
        # both MCP's structured result and its JSON text representation.
        return len(json.dumps(data, indent=2).encode("utf-8")) <= MAX_RESULT_BYTES

    # The most rows that fit, by bisection: one serialization per halving, not per row.
    low, high = 0, len(clipped)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    if not fits(low):
        raise Invalid("Result columns exceed the preview budget; select fewer columns in SQL.")
    table["truncated"] |= table["dropped_rows"] > 0 or clipped != original
    return type(answer).model_validate(data)
