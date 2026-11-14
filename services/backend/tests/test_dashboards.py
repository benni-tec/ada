"""Dashboards: versions and the pointer, revisions, layouts, pinning a copy of a widget and
the events, through the service; then the REST routes, the MCP tools and PostgreSQL."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import AsyncContainer
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError

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
from ada.core.ports.repositories import OperatorRepository, ProjectRepository, WidgetRepository
from ada.core.services.ports.dashboards import DashboardService
from api_support import Overrides, Seen, call, events, mcp_client, new_project, send, serve, store
from conftest import settings_in
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio

AGENT = factories.AGENT
WEB = {"kind": "user", "name": "web"}


def widget_in(memory: MemoryStore, project_id: Any, **changes: Any) -> Widget:
    """A widget in the store; the dashboard service reads widgets, it never makes them."""
    widget = Widget(
        **{
            "id": uuid7(),
            "project_id": UUID(str(project_id)),
            "operator_id": "op",
            "type": "value",
            "title": "Coverage",
            "created_by": AGENT,
            "created_at": factories.NOW,
            **changes,
        }
    )
    memory.widgets[widget.id] = widget
    return widget


# The service


@dataclass
class World:
    container: AsyncContainer
    memory: MemoryStore
    project_id: Id

    def widget(self, project_id: Id | None = None, **changes: Any) -> Widget:
        return widget_in(self.memory, project_id or self.project_id, **changes)

    async def events(self) -> list[Any]:
        return (await self.container.get(MemoryEventBus)).published

    async def run[T](self, work: Callable[[DashboardService], Awaitable[T]]) -> T:
        """One unit of work, as a request would be: events go out when it ends."""
        async with self.container() as request:
            return await work(await request.get(DashboardService))

    async def dashboard(self) -> Any:
        return await self.run(lambda s: s.create(self.project_id, "Overview", AGENT))


@pytest.fixture
async def world(unreachable_settings: Settings) -> AsyncIterator[World]:
    container = create_container(unreachable_settings, *memory_adapters())
    memory = await container.get(MemoryStore)
    project = factories.project()
    memory.projects[project.id] = project
    yield World(container, memory, project.id)
    await container.close()


async def test_each_edit_adds_a_version_and_moves_the_pointer(world: World) -> None:
    dashboard = await world.run(lambda s: s.create(world.project_id, "  Overview ", AGENT))
    assert (dashboard.name, dashboard.current_version_id) == ("Overview", None)
    assert dashboard.default_time_range == TimeRange()
    first, second = world.widget(title="First"), world.widget(title="Second")

    v1 = await world.run(
        lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=first.id)], 1, AGENT)
    )
    v2 = await world.run(
        lambda s: s.edit(
            dashboard.id,
            [Slot(name="a", widget_id=first.id), Slot(name=" b ", widget_id=second.id)],
            2,
            AGENT,
        )
    )

    assert (v1.number, v2.number) == (1, 2)
    assert await world.run(lambda s: s.versions(dashboard.id)) == [v1, v2]
    assert await world.run(lambda s: s.current(dashboard.id)) == v2
    stored = await world.run(lambda s: s.get(dashboard.id))
    assert (stored.current_version_id, stored.revision) == (v2.id, 3)
    # An old version is kept as it was; names are trimmed.
    assert [slot.name for slot in v1.slots] == ["a"]
    assert [slot.name for slot in v2.slots] == ["a", "b"]


async def test_a_refused_edit_adds_no_version_and_announces_nothing(world: World) -> None:
    dashboard = await world.dashboard()
    await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 1, AGENT))
    before = len(await world.events())
    foreign = world.widget(project_id=uuid7())

    with pytest.raises(Conflict) as raised:
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="b")], 1, AGENT))
    with pytest.raises(Invalid, match="unique"):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a"), Slot(name=" a ")], 2, AGENT)
        )
    with pytest.raises(Invalid, match="another project"):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=foreign.id)], 2, AGENT)
        )
    with pytest.raises(NotFound):
        await world.run(
            lambda s: s.edit(dashboard.id, [Slot(name="a", widget_id=uuid7())], 2, AGENT)
        )

    assert (raised.value.expected, raised.value.actual) == (1, 2)
    assert len(await world.run(lambda s: s.versions(dashboard.id))) == 1
    assert len(await world.events()) == before


async def test_slots_get_default_layouts_beside_each_other_then_on_a_new_row(
    world: World,
) -> None:
    dashboard = await world.dashboard()
    slots = [Slot(name="wide", layout={"w": 12, "h": 2}), *(Slot(name=n) for n in "abc")]

    version = await world.run(lambda s: s.edit(dashboard.id, slots, 1, AGENT))

    # A layout with keys left out is filled from the defaults.
    assert [slot.layout for slot in version.slots] == [
        {"x": 0, "y": 0, "w": 12, "h": 2},
        {"x": 0, "y": 2, "w": 6, "h": 4},
        {"x": 6, "y": 2, "w": 6, "h": 4},
        {"x": 0, "y": 6, "w": 6, "h": 4},
    ]


@pytest.mark.parametrize("layout", [{"x": 7, "w": 6}, {"z": 1}])
async def test_an_invalid_layout_is_refused(world: World, layout: dict[str, Any]) -> None:
    dashboard = await world.dashboard()

    with pytest.raises(Invalid):
        await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a", layout=layout)], 1, AGENT))


async def test_pinning_adds_a_slot_with_a_copy_of_the_first_original(world: World) -> None:
    session = factories.session(world.project_id)
    original = world.widget(session_id=session.id, spec={"column": "value"}, note="Why")
    pinner = AGENT.model_copy(update={"name": "someone else"})
    dashboard = await world.dashboard()

    version = await world.run(
        lambda s: s.pin_widget(dashboard.id, original.id, "coverage", 1, pinner)
    )
    copy = world.memory.widgets[version.slots[0].widget_id]  # type: ignore[index]
    again = await world.run(lambda s: s.pin_widget(dashboard.id, copy.id, "again", 2, pinner))

    assert [slot.name for slot in version.slots] == ["coverage"]
    assert copy.id != original.id
    assert (copy.operator_id, copy.spec, copy.title, copy.note) == (
        original.operator_id,
        original.spec,
        original.title,
        original.note,
    )
    assert (copy.copied_from, copy.session_id, copy.created_by) == (original.id, None, pinner)
    # The original is untouched and stays in its session.
    assert world.memory.widgets[original.id] == original
    # A copy pinned again is copied from the first original.
    second_copy = world.memory.widgets[again.slots[1].widget_id]  # type: ignore[index]
    assert second_copy.copied_from == original.id


async def test_pinning_into_an_existing_slot_changes_its_widget_and_keeps_its_place(
    world: World,
) -> None:
    dashboard = await world.dashboard()
    old, new, other = world.widget(), world.widget(), world.widget()
    await world.run(lambda s: s.pin_widget(dashboard.id, old.id, "main", 1, AGENT))
    await world.run(lambda s: s.pin_widget(dashboard.id, other.id, "side", 2, AGENT))

    version = await world.run(lambda s: s.pin_widget(dashboard.id, new.id, "main", 3, AGENT))

    assert [
        (slot.name, world.memory.widgets[slot.widget_id].copied_from)  # type: ignore[index]
        for slot in version.slots
    ] == [("main", new.id), ("side", other.id)]
    assert version.slots[0].layout == {"x": 0, "y": 0, "w": 6, "h": 4}


async def test_a_refused_pin_copies_nothing(world: World) -> None:
    dashboard = await world.dashboard()
    widget = world.widget()
    foreign = world.widget(project_id=uuid7())

    with pytest.raises(Conflict):
        await world.run(lambda s: s.pin_widget(dashboard.id, widget.id, "a", 7, AGENT))
    with pytest.raises(Invalid, match="another project"):
        await world.run(lambda s: s.pin_widget(dashboard.id, foreign.id, "a", 1, AGENT))
    with pytest.raises(Invalid):
        await world.run(lambda s: s.pin_widget(dashboard.id, widget.id, "  ", 1, AGENT))

    assert await world.run(lambda s: s.versions(dashboard.id)) == []
    assert len(world.memory.widgets) == 2


async def test_the_default_time_range_is_a_revisioned_change_without_a_new_version(
    world: World,
) -> None:
    dashboard = await world.dashboard()
    version = await world.run(lambda s: s.edit(dashboard.id, [Slot(name="a")], 1, AGENT))
    window = TimeRange(start=date(2020, 1, 1), end=date(2024, 12, 31))

    # The edit moved the revision: a range set from the read before it is refused.
    with pytest.raises(Conflict):
        await world.run(lambda s: s.set_default_time_range(dashboard.id, window, 1))
    saved = await world.run(lambda s: s.set_default_time_range(dashboard.id, window, 2))

    assert (saved.default_time_range, saved.revision) == (window, 3)
    assert await world.run(lambda s: s.versions(dashboard.id)) == [version]
    last = (await world.events())[-1]
    assert (last.type, last.payload["version_id"]) == (EventType.DASHBOARD_CHANGED, str(version.id))
    with pytest.raises(Invalid, match="ends before"):
        backwards = TimeRange(start=date(2024, 1, 1), end=date(2020, 1, 1))
        await world.run(lambda s: s.set_default_time_range(dashboard.id, backwards, 3))


async def test_every_new_version_is_announced_after_the_commit(world: World) -> None:
    dashboard = await world.dashboard()
    widget = world.widget()

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
    assert events[1].payload == {"widget_id": str(version.slots[0].widget_id)}
    assert events[2].payload == {"dashboard_id": str(dashboard.id), "version_id": str(version.id)}
    assert events[2].project_id == world.project_id


# REST


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


def create_dashboard(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return send(client, "POST", f"/projects/{project['id']}/dashboards", {"name": "Overview"}, 201)


def test_pinning_answers_with_the_new_state_or_a_conflict_naming_both_revisions(
    client: TestClient,
) -> None:
    project = new_project(client)
    dashboard = create_dashboard(client, project)
    widget = widget_in(store(client), project["id"])
    pin = {"widget_id": str(widget.id), "slot": "coverage", "expected_revision": 1}

    pinned = send(client, "POST", f"/dashboards/{dashboard['id']}/pins", pin, 201)
    stale = client.post(f"/api/dashboards/{dashboard['id']}/pins", json=pin)

    assert pinned["dashboard"]["revision"] == 2
    assert pinned["dashboard"]["current_version_id"] == pinned["version"]["id"]
    assert pinned["version"]["created_by"] == WEB
    copy_id = pinned["version"]["slots"][0]["widget_id"]
    assert pinned["version"]["slots"] == [
        {
            "name": "coverage",
            "description": "",
            "widget_id": copy_id,
            "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
        }
    ]
    assert send(client, "GET", f"/widgets/{copy_id}")["copied_from"] == str(widget.id)
    assert send(client, "GET", f"/dashboards/{dashboard['id']}") == pinned
    assert stale.status_code == 409
    assert (stale.json()["expected_revision"], stale.json()["revision"]) == (1, 2)
    changes = [e for e in events(client, project["id"]) if e.type is EventType.DASHBOARD_CHANGED]
    assert [e.payload["version_id"] for e in changes] == [None, pinned["version"]["id"]]


def test_a_run_for_a_dashboard_uses_its_range_unless_one_is_given(client: TestClient) -> None:
    project = new_project(client)
    dashboard = create_dashboard(client, project)
    send(
        client,
        "PATCH",
        f"/dashboards/{dashboard['id']}",
        {"default_time_range": {"start": "2020-01-01", "end": None}, "expected_revision": 1},
    )

    default = send(client, "POST", f"/dashboards/{dashboard['id']}/runs", None, 201)
    given = send(
        client,
        "POST",
        f"/dashboards/{dashboard['id']}/runs",
        {"time_range": {"start": "2022-01-01", "end": "2022-12-31"}},
        201,
    )

    assert default["project_id"] == project["id"]
    assert default["time_range"] == {"start": "2020-01-01", "end": None}
    assert given["time_range"] == {"start": "2022-01-01", "end": "2022-12-31"}
    assert default["started_by"] == WEB
    bad_layout = {"slots": [{"name": "a", "layout": {"x": 9, "w": 6}}], "expected_revision": 2}
    response = client.put(f"/api/dashboards/{dashboard['id']}/slots", json=bad_layout)
    assert (response.status_code, "grid" in response.json()["detail"]) == (422, True)


def test_a_dashboard_has_one_agent_session_the_newest_that_shows_it(client: TestClient) -> None:
    project = new_project(client)
    dashboard = create_dashboard(client, project)
    path = f"/api/dashboards/{dashboard['id']}/agent-session"
    sessions = f"/projects/{project['id']}/sessions"
    # A session that only comes from the dashboard is not its panel's.
    from_here = {"title": "Explore", "origin_dashboard_id": dashboard["id"]}
    started_here = send(client, "POST", sessions, from_here, 201)

    created = client.post(path)
    found = client.post(path)
    newer = send(client, "POST", sessions, from_here, 201)
    shown = {"expected_revision": 1, "panel_dashboard_id": dashboard["id"]}
    send(client, "PATCH", f"/sessions/{newer['id']}", shown)
    newest = client.post(path)

    assert (created.status_code, found.status_code) == (201, 200)
    session = created.json()
    assert found.json() == session != started_here
    assert session["title"] == f"{dashboard['name']} (agent)"
    assert session["origin_dashboard_id"] == session["panel_dashboard_id"] == dashboard["id"]
    assert newest.json()["id"] == newer["id"]
    assert client.post(f"/api/dashboards/{uuid7()}/agent-session").status_code == 404


# MCP


@pytest.fixture(scope="module")
async def agent(unreachable_settings: Settings) -> AsyncIterator[tuple[Client, Seen]]:
    async with mcp_client(unreachable_settings) as agent:
        yield agent


async def test_the_dashboard_tools_are_served_and_documented(agent: tuple[Client, Seen]) -> None:
    client, _ = agent
    tools = {tool.name: tool for tool in await client.list_tools()}
    expected = {
        "create_dashboard",
        "list_dashboards",
        "get_dashboard",
        "list_dashboard_versions",
        "pin_widget",
        "edit_dashboard",
        "set_dashboard_time_range",
        "show_dashboard_in_session",
    }
    assert expected <= set(tools)
    for name in expected:
        assert len(tools[name].description or "") > 80, name
    # Every write names the revision it was read at.
    for name in ("pin_widget", "edit_dashboard", "set_dashboard_time_range"):
        assert "expected_revision" in tools[name].input_schema["required"], name


async def test_an_agent_pins_a_widget_and_shows_the_dashboard_in_its_session(
    agent: tuple[Client, Seen],
) -> None:
    client, seen = agent
    project = await call(client, "create_project", name="Wellbeing")
    created = await call(client, "create_dashboard", project_id=project["id"], name="Overview")
    dashboard_id = created["dashboard"]["id"]
    assert created["url"] == f"/projects/{project['id']}/dashboards/{dashboard_id}"
    widget = widget_in(await seen.container.get(MemoryStore), project["id"])
    pin = {"dashboard_id": dashboard_id, "widget_id": str(widget.id), "slot": "coverage"}

    pinned = await call(client, "pin_widget", **pin, expected_revision=1)
    with pytest.raises(ToolError, match="revision 2.*expected revision 1"):
        await call(client, "pin_widget", **pin, expected_revision=1)
    session = await call(client, "create_session", project_id=project["id"], title="Look")
    shown = await call(
        client,
        "show_dashboard_in_session",
        session_id=session["id"],
        dashboard_id=dashboard_id,
        expected_revision=session["revision"],
    )

    assert pinned["version"]["created_by"] == {"kind": "external_agent", "name": "claude-code"}
    assert await call(client, "get_dashboard", dashboard_id=dashboard_id) == pinned
    assert shown["session"]["panel_dashboard_id"] == dashboard_id
    assert shown["url"] == f"/projects/{project['id']}/sessions/{session['id']}"
    elsewhere = await call(client, "create_project", name="Elsewhere")
    foreign = await call(client, "create_session", project_id=elsewhere["id"], title="Look")
    with pytest.raises(ToolError, match="another project"):
        await call(
            client,
            "show_dashboard_in_session",
            session_id=foreign["id"],
            dashboard_id=dashboard_id,
            expected_revision=1,
        )


# PostgreSQL


async def test_versions_and_the_pointer_commit_together_and_a_conflict_rolls_back(
    migrated_database_url: str, tmp_path: Path
) -> None:
    container = create_container(settings_in(tmp_path, migrated_database_url), MemoryBackground())
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
            # The database keeps a widget's operator, so it comes first.
            operator = factories.operator(project.id)
            await (await request.get(OperatorRepository)).add(operator)
            widget = widget_in(MemoryStore(), project.id, operator_id=operator.id)
            await (await request.get(WidgetRepository)).add(widget)

        async def pin(slot: str, revision: int) -> Any:
            async with container() as request:
                service = await request.get(DashboardService)
                return await service.pin_widget(dashboard.id, widget.id, slot, revision, AGENT)

        async with container() as request:
            dashboard = await (await request.get(DashboardService)).create(
                project.id, "Overview", AGENT
            )
        first = await pin("a", 1)
        # A stale writer is refused and leaves no version behind.
        with pytest.raises(Conflict):
            await pin("b", 1)
        second = await pin("b", 2)
        async with container() as request:
            service = await request.get(DashboardService)
            stored = await service.get(dashboard.id)
            versions = await service.versions(dashboard.id)
    finally:
        await container.close()

    assert [v.id for v in versions] == [first.id, second.id]
    assert (stored.current_version_id, stored.revision) == (second.id, 3)
    assert [(s.name, s.layout) for s in second.slots] == [
        ("a", {"x": 0, "y": 0, "w": 6, "h": 4}),
        ("b", {"x": 6, "y": 0, "w": 6, "h": 4}),
    ]
