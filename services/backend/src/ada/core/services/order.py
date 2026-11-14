"""Putting a project's dashboards or reports in the order people want them."""

from collections.abc import Sequence
from datetime import datetime

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType


def check_order(kind: str, current: Sequence[Id], ids: Sequence[Id]) -> None:
    """A new order names every one of the project's records once, and nothing else."""
    if len(ids) != len(set(ids)) or set(ids) != set(current):
        raise Invalid(
            f"A new order lists every {kind} of the project once: {len(current)} of them,"
            f" got {len(ids)} ids"
        )


def order_changed(project_id: Id, list_name: str, at: datetime) -> Event:
    return Event(
        type=EventType.ORDER_CHANGED, project_id=project_id, payload={"list": list_name}, at=at
    )
