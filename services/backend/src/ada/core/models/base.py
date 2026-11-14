from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

type JsonObject = dict[str, Any]

# Ids are UUIDv7, so they sort by creation time. Operators are the exception: their id is
# their identity hash (operators.py).
type Id = UUID


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True)
