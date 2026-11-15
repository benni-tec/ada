"""Pinning a project's dashboards or reports, in the order people want them: the pinned ones
come first in that order, the rest after them in creation order. Only people change it."""

from collections.abc import Sequence
from datetime import datetime

from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event, EventType


def check_order(kind: str, current: Sequence[Id], ids: Sequence[Id]) -> None:
    """The pinned ones: each once, and only the project's own."""
    if len(ids) != len(set(ids)):
        raise Invalid(f"Each pinned {kind} is listed once")
    unknown = set(ids) - set(current)
    if unknown:
        raise Invalid(f"Not a {kind} of the project: {', '.join(sorted(map(str, unknown)))}")


def order_changed(project_id: Id, list_name: str, at: datetime) -> Event:
    return Event(
        type=EventType.ORDER_CHANGED, project_id=project_id, payload={"list": list_name}, at=at
    )
