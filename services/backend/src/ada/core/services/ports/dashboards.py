from collections.abc import Sequence
from typing import Protocol

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.time import TimeRange


class DashboardService(Protocol):
    async def create(self, project_id: Id, name: str, actor: Actor) -> Dashboard: ...
    async def get(self, id: Id) -> Dashboard: ...
    async def list(self, project_id: Id) -> Sequence[Dashboard]: ...

    async def current(self, id: Id) -> DashboardVersion | None:
        """The version the dashboard points at; None before its first edit."""
        ...

    async def version(self, version_id: Id) -> DashboardVersion: ...
    async def versions(self, id: Id) -> Sequence[DashboardVersion]: ...

    async def edit(
        self, id: Id, slots: Sequence[Slot], expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        """Replace the dashboard's slots. Adds a version and points the dashboard at it.
        A slot may hold any widget of the dashboard's project: one that was never on this
        dashboard is copied on the way in, as `pin_widget` copies it."""
        ...

    async def pin_widget(
        self,
        id: Id,
        widget_id: Id,
        slot: str,
        expected_revision: int,
        actor: Actor,
        layout: JsonObject | None = None,
    ) -> DashboardVersion:
        """Put a copy of a widget, e.g. one from a session, into a slot; the slot is added
        when the dashboard has none of that name. The copy has the same operator, type,
        spec, title and note, no session, `copied_from` naming the original, and is
        created by `actor`, so the dashboard's widget can change on its own. `layout`
        places the slot; without it a slot keeps its place and a new one goes after the
        others."""
        ...

    async def set_default_time_range(
        self, id: Id, time_range: TimeRange, expected_revision: int
    ) -> Dashboard: ...
