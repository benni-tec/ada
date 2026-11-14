from enum import Enum
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

type JsonObject = dict[str, Any]

# Ids are UUIDv7, so they sort by creation time. Operators are the exception: their id is
# their identity hash (operators.py).
type Id = UUID


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Unchanged(Enum):
    """An update argument that was not given. Needed where None is a value of its own: for
    a field that may be empty, None clears it, and leaving it out keeps it."""

    UNCHANGED = "unchanged"


UNCHANGED: Final = Unchanged.UNCHANGED

# A field of an update: its new value, or UNCHANGED.
type Change[T] = T | Literal[Unchanged.UNCHANGED]
