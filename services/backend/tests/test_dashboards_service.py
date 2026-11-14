"""DashboardService: versions, the pointer, revisions, pinning and the events."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid7

import pytest
from dishka import AsyncContainer

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.base import Id
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Conflict, Invalid, NotFound
from ada.core.models.events import EventType
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.services.dashboards.layout import COLUMNS
from ada.core.services.ports.dashboards import DashboardService
from memory import memory_adapters

pytestmark = pytest.mark.anyio

AGENT = factories.AGENT


@dataclass
class World:
    container: AsyncContainer
    project_id: Id

    async def widget(self, project_id: Id | None = None, **changes: Any) -> Widget:
        """A widget in the store; the service reads widgets, it never makes them."""
        widget = Widget(
            **{
                "id": uuid7(),
                "project_id": project_id or self.project_id,
                "operator_id": "op",
                "type": "value",
                "title": "Coverage",
                "created_by": AGENT,
                "created_at": factories.NOW,
                **changes,
            }
        )
        (await self.container.get(MemoryStore)).widgets[widget.id] = widget
        return widget

    async def events(self) -> list[Any]:
        return (await self.container.get(MemoryEventBus)).published

    async def run[T](self, work: Callable[[DashboardService], Awaitable[T]]) -> T:
        """One unit of work, as a request would be: events go out when it ends."""
        async with self.container() as request:
            return await work(await request.get(DashboardService))


@pytest.fixture
async def world(unreachable_settings: Settings) -> AsyncIterator[World]:
    container = create_container(unreachable_settings, *memory_adapters())
    project = factories.project()
    (await container.get(MemoryStore)).projects[project.id] = project
    yield World(container, project.id)
    await container.close()


async def test_a_new_dashboard_has_no_version_and_an_open_range(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "  Overview ", AGENT))

    assert (dashboard.name, dashboard.revision, dashboard.current_version_id) == (
        "Overview",
        1,
        None,
    )
    assert dashboard.default_time_range == TimeRange()
    assert await world.run(lambda s: s.current(dashboard.id)) is None
    assert await world.run(lambda s: s.versions(dashboard.id)) == []
    assert await world.run(lambda s: s.list(world.project_id)) == [dashboard]


async def test_a_dashboard_needs_a_name_and_a_project(world: World) -> None:
    with pytest.raises(Invalid):
        await world.run(lambda s: s.create(world.project_id, "   ", AGENT))
    with pytest.raises(NotFound):
        await world.run(lambda s: s.create(uuid7(), "x", AGENT))
    with pytest.raises(NotFound):
        await world.run(lambda s: s.list(uuid7()))
    with pytest.raises(NotFound):
        await world.run(lambda s: s.get(uuid7()))


async def test_each_edit_adds_a_version_and_moves_the_pointer(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    first = await world.widget(title="First")
    second = await world.widget(title="Second")

    v1 = await world.run(
        lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=first.id)], 1, AGENT)
    )
    v2 = await world.run(
        lambda s: s.edit(
            dashboard.id,
            [Slot(name="a", widget_id=first.id), Slot(name="b", widget_id=second.id)],
            2,
            AGENT,
        )
    )

    assert (v1.number, v2.number) == (1, 2)
    assert v1.created_by == AGENT
    assert await world.run(lambda s: s.versions(dashboard.id)) == [v1, v2]
    assert await world.run(lambda s: s.current(dashboard.id)) == v2
    assert await world.run(lambda s: s.version(v1.id)) == v1
    stored = await world.run(lambda s: s.get(dashboard.id))
    assert (stored.current_version_id, stored.revision) == (v2.id, 3)
    # An old version is kept as it was.
    assert [slot.name for slot in v1.slots] == ["a"]


async def test_a_stale_revision_conflicts_and_adds_no_version(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 1, AGENT))

    with pytest.raises(Conflict) as raised:
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="b")], 1, AGENT))
    assert (raised.value.expected, raised.value.actual) == (1, 2)
    assert len(await world.run(lambda s: s.versions(dashboard.id))) == 1
    current = await world.run(lambda s: s.current(dashboard.id))
    assert current is not None
    assert [slot.name for slot in current.slots] == ["a"]


async def test_slots_get_default_layouts_beside_each_other_then_on_a_new_row(
    world: World,
) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    names = ["a", "b", "c", "d", "e"]

    version = await world.run(
        lambda s: s.edit(dashboard.id, [Slot(name=name) for name in names], 1, AGENT)
    )

    assert [slot.layout for slot in version.slots] == [
        {"x": 0, "y": 0, "w": 6, "h": 4},
        {"x": 6, "y": 0, "w": 6, "h": 4},
        {"x": 0, "y": 4, "w": 6, "h": 4},
        {"x": 6, "y": 4, "w": 6, "h": 4},
        {"x": 0, "y": 8, "w": 6, "h": 4},
    ]


async def test_a_layout_with_keys_left_out_is_filled_from_the_defaults(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))

    version = await world.run(
        lambda s: s.edit(
            dashboard.id,
            [Slot(name="wide", layout={"w": 12, "h": 2}), Slot(name="next")],
            1,
            AGENT,
        )
    )

    assert version.slots[0].layout == {"x": 0, "y": 0, "w": 12, "h": 2}
    # Twelve columns are used, so the next card starts a row below.
    assert version.slots[1].layout == {"x": 0, "y": 2, "w": 6, "h": 4}


@pytest.mark.parametrize(
    "layout",
    [
        {"x": -1},
        {"x": 7, "w": 6},
        {"x": 0, "w": COLUMNS + 1},
        {"w": 0},
        {"h": 0},
        {"y": -2},
        {"x": 1.5},
        {"x": True},
        {"x": "0"},
        {"z": 1},
    ],
)
async def test_an_invalid_layout_is_refused(world: World, layout: dict[str, Any]) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))

    with pytest.raises(Invalid):
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a", layout=layout)], 1, AGENT))
    assert await world.run(lambda s: s.versions(dashboard.id)) == []


async def test_slot_names_are_trimmed_unique_and_not_blank(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))

    with pytest.raises(Invalid, match="unique"):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a"), Slot(name=" a ")], 1, AGENT)
        )
    with pytest.raises(Invalid):
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name=" ")], 1, AGENT))
    version = await world.run(lambda s: s.edit(dashboard.id, [Slot(name=" a ")], 1, AGENT))
    assert version.slots[0].name == "a"


async def test_a_slot_needs_a_widget_of_the_same_project(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    foreign = await world.widget(project_id=uuid7())

    with pytest.raises(Invalid, match="another project"):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=foreign.id)], 1, AGENT)
        )
    with pytest.raises(NotFound):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=uuid7())], 1, AGENT)
        )


async def test_pinning_adds_a_slot_with_a_copy_of_the_widget(world: World) -> None:
    session = factories.session(world.project_id)
    original = await world.widget(
        session_id=session.id, spec={"column": "value"}, note="Why", type="table"
    )
    pinner = factories.AGENT.model_copy(update={"name": "someone else"})
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))

    version = await world.run(
        lambda s: s.pin_widget(dashboard.id, original.id, "coverage", 1, pinner)
    )

    store = await world.container.get(MemoryStore)
    copy = store.widgets[version.slots[0].widget_id]  # type: ignore[index]
    assert [slot.name for slot in version.slots] == ["coverage"]
    assert version.slots[0].layout == {"x": 0, "y": 0, "w": 6, "h": 4}
    assert copy.id != original.id
    assert (copy.operator_id, copy.type, copy.spec, copy.title, copy.note) == (
        original.operator_id,
        original.type,
        original.spec,
        original.title,
        original.note,
    )
    assert (copy.copied_from, copy.session_id, copy.created_by) == (original.id, None, pinner)
    # The original is untouched and stays in its session.
    assert store.widgets[original.id] == original


async def test_a_copy_pinned_again_points_at_the_first_original(world: World) -> None:
    original = await world.widget()
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    first = await world.run(lambda s: s.pin_widget(dashboard.id, original.id, "a", 1, AGENT))
    copy_id = first.slots[0].widget_id
    assert copy_id is not None

    second = await world.run(lambda s: s.pin_widget(dashboard.id, copy_id, "b", 2, AGENT))

    store = await world.container.get(MemoryStore)
    again = store.widgets[second.slots[1].widget_id]  # type: ignore[index]
    assert again.id not in (original.id, copy_id)
    assert again.copied_from == original.id


async def test_pinning_into_an_existing_slot_changes_its_widget_and_keeps_its_place(
    world: World,
) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    old, new, other = await world.widget(), await world.widget(), await world.widget()
    await world.run(lambda s: s.pin_widget(dashboard.id, old.id, "main", 1, AGENT))
    await world.run(lambda s: s.pin_widget(dashboard.id, other.id, "side", 2, AGENT))

    version = await world.run(lambda s: s.pin_widget(dashboard.id, new.id, "main", 3, AGENT))

    store = await world.container.get(MemoryStore)
    assert version.number == 3
    assert [
        (slot.name, store.widgets[slot.widget_id].copied_from)  # type: ignore[index]
        for slot in version.slots
    ] == [("main", new.id), ("side", other.id)]
    assert version.slots[0].layout == {"x": 0, "y": 0, "w": 6, "h": 4}


async def test_pinning_checks_revision_and_project(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    widget = await world.widget()
    foreign = await world.widget(project_id=uuid7())

    with pytest.raises(Conflict):
        await world.run(lambda s: s.pin_widget(dashboard.id, widget.id, "a", 7, AGENT))
    with pytest.raises(Invalid, match="another project"):
        await world.run(lambda s: s.pin_widget(dashboard.id, foreign.id, "a", 1, AGENT))
    with pytest.raises(Invalid):
        await world.run(lambda s: s.pin_widget(dashboard.id, widget.id, "  ", 1, AGENT))
    assert await world.run(lambda s: s.versions(dashboard.id)) == []
    # A refused pin copies nothing either.
    assert len((await world.container.get(MemoryStore)).widgets) == 2


async def test_the_default_time_range_is_a_revisioned_change_without_a_new_version(
    world: World,
) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    window = TimeRange(start=date(2020, 1, 1), end=date(2024, 12, 31))

    saved = await world.run(lambda s: s.set_default_time_range(dashboard.id, window, 1))

    assert (saved.default_time_range, saved.revision) == (window, 2)
    assert await world.run(lambda s: s.versions(dashboard.id)) == []
    with pytest.raises(Conflict):
        await world.run(lambda s: s.set_default_time_range(dashboard.id, window, 1))
    with pytest.raises(Invalid, match="ends before"):
        await world.run(
            lambda s: s.set_default_time_range(
                dashboard.id, TimeRange(start=date(2024, 1, 1), end=date(2020, 1, 1)), 2
            )
        )
    # Open on one side or both is fine.
    await world.run(lambda s: s.set_default_time_range(dashboard.id, TimeRange(), 2))


async def test_an_edit_moves_the_revision_that_a_time_range_change_must_send(
    world: World,
) -> None:
    # Both write the same record, so a person who set the range from an old read must be
    # refused after an agent edited the slots.
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 1, AGENT))

    with pytest.raises(Conflict):
        await world.run(lambda s: s.set_default_time_range(dashboard.id, TimeRange(), 1))


async def test_every_new_version_is_announced_after_the_commit(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    widget = await world.widget()

    async with world.container() as request:
        service = await request.get(DashboardService)
        version = await service.pin_widget(dashboard.id, widget.id, "a", 1, AGENT)
        # Nothing has gone out while the unit of work is open.
        assert [e.type for e in await world.events()] == [EventType.DASHBOARD_CHANGED]

    events = await world.events()
    # The copy is a new widget, announced like any other.
    assert [e.type for e in events] == [
        EventType.DASHBOARD_CHANGED,
        EventType.WIDGET_CREATED,
        EventType.DASHBOARD_CHANGED,
    ]
    assert events[0].payload == {"dashboard_id": str(dashboard.id), "version_id": None}
    assert events[1].payload == {"widget_id": str(version.slots[0].widget_id)}
    assert events[2].payload == {
        "dashboard_id": str(dashboard.id),
        "version_id": str(version.id),
    }
    assert events[2].project_id == world.project_id


async def test_a_refused_edit_announces_nothing(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    before = len(await world.events())

    with pytest.raises(Conflict):
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 9, AGENT))
    with pytest.raises(Invalid):
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="")], 1, AGENT))

    assert len(await world.events()) == before


async def test_a_time_range_change_is_announced_with_the_current_version(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "Overview", AGENT))
    version = await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 1, AGENT))

    await world.run(lambda s: s.set_default_time_range(dashboard.id, TimeRange(), 2))

    last = (await world.events())[-1]
    assert last.type is EventType.DASHBOARD_CHANGED
    assert last.payload["version_id"] == str(version.id)
