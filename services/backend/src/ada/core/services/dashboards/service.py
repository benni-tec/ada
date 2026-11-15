from collections.abc import Sequence
from uuid import uuid7

from ada.core.models.actors import Actor
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, DashboardVersion, Slot
from ada.core.models.errors import Conflict, Invalid
from ada.core.models.events import Event, EventType
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.events import EventPublisher
from ada.core.ports.repositories import (
    DashboardRepository,
    ProjectRepository,
    WidgetRepository,
)
from ada.core.ports.system import Clock
from ada.core.services.dashboards.layout import complete_layout
from ada.core.services.order import check_order, order_changed
from ada.core.services.ports.dashboards import DashboardService


class Dashboards(DashboardService):
    def __init__(
        self,
        dashboards: DashboardRepository,
        projects: ProjectRepository,
        widgets: WidgetRepository,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        self.dashboards = dashboards
        self.projects = projects
        self.widgets = widgets
        self.events = events
        self.clock = clock

    async def create(self, project_id: Id, name: str, actor: Actor) -> Dashboard:
        await self.projects.get(project_id)
        dashboard = Dashboard(
            id=uuid7(), project_id=project_id, name=_name(name), created_at=self.clock.now()
        )
        await self.dashboards.add(dashboard)
        # Announced so a project page lists a dashboard an agent created over MCP; it has
        # no version yet.
        await self._announce(dashboard, None)
        return dashboard

    async def get(self, id: Id) -> Dashboard:
        return await self.dashboards.get(id)

    async def list(self, project_id: Id) -> Sequence[Dashboard]:
        # Read the project first, so an unknown id is a 404 and not an empty list.
        await self.projects.get(project_id)
        return await self.dashboards.list(project_id)

    async def reorder(self, project_id: Id, ids: Sequence[Id]) -> Sequence[Dashboard]:
        current = await self.list(project_id)
        check_order("dashboard", [dashboard.id for dashboard in current], ids)
        await self.dashboards.reorder(project_id, ids)
        await self.events.publish(order_changed(project_id, "dashboards", self.clock.now()))
        return await self.dashboards.list(project_id)

    async def current(self, id: Id) -> DashboardVersion | None:
        dashboard = await self.dashboards.get(id)
        if dashboard.current_version_id is None:
            return None
        return await self.dashboards.get_version(dashboard.current_version_id)

    async def version(self, version_id: Id) -> DashboardVersion:
        return await self.dashboards.get_version(version_id)

    async def versions(self, id: Id) -> Sequence[DashboardVersion]:
        await self.dashboards.get(id)
        return await self.dashboards.versions(id)

    async def edit(
        self, id: Id, slots: Sequence[Slot], expected_revision: int, actor: Actor
    ) -> DashboardVersion:
        dashboard = await self.dashboards.get(id)
        placed = await self._placed(dashboard, slots)
        # Checked before anything is written, so a stale caller adds no copy either.
        if dashboard.revision != expected_revision:
            raise Conflict("dashboard", id, expected_revision, dashboard.revision)
        # A widget that was never on this dashboard, e.g. one made in a session, comes in
        # as the dashboard's own copy, as when it is pinned: once per widget, however many
        # slots show it.
        own = {
            slot.widget_id
            for version in await self.dashboards.versions(id)
            for slot in version.slots
            if slot.widget_id is not None
        }
        copies: dict[Id, Id] = {}
        for slot in placed:
            if slot.widget_id is None or slot.widget_id in own or slot.widget_id in copies:
                continue
            original = await self.widgets.get(slot.widget_id)
            copies[slot.widget_id] = (await self._copy(original, actor)).id
        placed = tuple(
            slot.model_copy(update={"widget_id": copies[slot.widget_id]})
            if slot.widget_id in copies
            else slot
            for slot in placed
        )
        return await self._add_version(dashboard, placed, expected_revision, actor)

    async def pin_widget(
        self,
        id: Id,
        widget_id: Id,
        slot: str,
        expected_revision: int,
        actor: Actor,
        layout: JsonObject | None = None,
    ) -> DashboardVersion:
        dashboard = await self.dashboards.get(id)
        name = _slot_name(slot)
        # Checked before anything is written, so a stale caller adds no copy either.
        if dashboard.revision != expected_revision:
            raise Conflict("dashboard", id, expected_revision, dashboard.revision)
        original = await self.widgets.get(widget_id)
        if original.project_id != dashboard.project_id:
            raise Invalid("The widget belongs to another project than the dashboard")
        current = await self.current(id)
        slots = list(current.slots) if current else []
        pinned: JsonObject = {"widget_id": original.id}
        if layout is not None:
            pinned["layout"] = layout
        for index, existing in enumerate(slots):
            if existing.name == name:
                # A pinned slot keeps its place unless given a layout; what it shows changes.
                slots[index] = existing.model_copy(update=pinned)
                break
        else:
            slots.append(Slot(name=name).model_copy(update=pinned))
        # Placed, and so checked, before the copy exists.
        placed = await self._placed(dashboard, slots)
        copy = await self._copy(original, actor)
        placed = tuple(
            entry.model_copy(update={"widget_id": copy.id}) if entry.name == name else entry
            for entry in placed
        )
        return await self._add_version(dashboard, placed, expected_revision, actor)

    async def _copy(self, original: Widget, actor: Actor) -> Widget:
        """The dashboard's own copy of a widget, so it can be changed without changing the
        session it came from. It points at the original, the widget made in a session:
        pinning a copy again copies that original's pointer, so one step always leads back
        to the session."""
        copy = Widget(
            id=uuid7(),
            project_id=original.project_id,
            operator_id=original.operator_id,
            inputs=original.inputs,
            verdict=original.verdict,
            type=original.type,
            title=original.title,
            spec=original.spec,
            note=original.note,
            created_by=actor,
            created_at=self.clock.now(),
            copied_from=original.copied_from or original.id,
        )
        await self.widgets.add(copy)
        await self.events.publish(
            Event(
                type=EventType.WIDGET_CREATED,
                project_id=copy.project_id,
                payload={"widget_id": str(copy.id)},
                at=self.clock.now(),
            )
        )
        return copy

    async def rename(self, id: Id, name: str, expected_revision: int) -> Dashboard:
        dashboard = await self.dashboards.get(id)
        saved = await self.dashboards.update(
            dashboard.model_copy(update={"name": _name(name)}), expected_revision
        )
        await self._announce(saved, saved.current_version_id)
        return saved

    async def set_default_time_range(
        self, id: Id, time_range: TimeRange, expected_revision: int
    ) -> Dashboard:
        if (
            time_range.start is not None
            and time_range.end is not None
            and time_range.start > time_range.end
        ):
            raise Invalid("The time range ends before it starts")
        dashboard = await self.dashboards.get(id)
        saved = await self.dashboards.update(
            dashboard.model_copy(update={"default_time_range": time_range}), expected_revision
        )
        await self._announce(saved, saved.current_version_id)
        return saved

    async def _placed(self, dashboard: Dashboard, slots: Sequence[Slot]) -> tuple[Slot, ...]:
        """The slots checked and with their layouts completed, in order. A slot's widget
        must be in the dashboard's project: a dashboard shows its own project's pipelines."""
        placed: list[Slot] = []
        names: set[str] = set()
        for slot in slots:
            name = _slot_name(slot.name)
            if name in names:
                raise Invalid(f"Two slots are called {name!r}; slot names are unique")
            names.add(name)
            if slot.widget_id is not None:
                widget = await self.widgets.get(slot.widget_id)
                if widget.project_id != dashboard.project_id:
                    raise Invalid("The widget belongs to another project than the dashboard")
            named = slot.model_copy(update={"name": name})
            placed.append(named.model_copy(update={"layout": complete_layout(named, placed)}))
        return tuple(placed)

    async def _add_version(
        self,
        dashboard: Dashboard,
        slots: tuple[Slot, ...],
        expected_revision: int,
        actor: Actor,
    ) -> DashboardVersion:
        previous = await self.dashboards.versions(dashboard.id)
        version = DashboardVersion(
            id=uuid7(),
            dashboard_id=dashboard.id,
            number=previous[-1].number + 1 if previous else 1,
            slots=slots,
            template_id=previous[-1].template_id if previous else None,
            created_by=actor,
            created_at=self.clock.now(),
        )
        # The pointer moves first: it is the revision-checked write, and a stale caller
        # must be refused before a version exists for it.
        moved = await self.dashboards.update(
            dashboard.model_copy(update={"current_version_id": version.id}), expected_revision
        )
        await self.dashboards.add_version(version)
        await self._announce(moved, version.id)
        return version

    async def _announce(self, dashboard: Dashboard, version_id: Id | None) -> None:
        await self.events.publish(
            Event(
                type=EventType.DASHBOARD_CHANGED,
                project_id=dashboard.project_id,
                payload={
                    "dashboard_id": str(dashboard.id),
                    "version_id": str(version_id) if version_id else None,
                },
                at=self.clock.now(),
            )
        )


def _name(name: str) -> str:
    name = name.strip()
    if not name:
        raise Invalid("A dashboard needs a name")
    return name


def _slot_name(name: str) -> str:
    # Slots are addressed by name, so a blank one could not be pinned to again.
    name = name.strip()
    if not name:
        raise Invalid("A slot needs a name")
    return name
