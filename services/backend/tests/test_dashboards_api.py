"""The REST routes and MCP tools of dashboards, on the memory adapters; the transactional
behaviour is checked against PostgreSQL at the end."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Conflict
from ada.core.models.events import EventType
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import (
    OperatorRepository,
    ProjectRepository,
    WidgetRepository,
)
from ada.core.services.ports.dashboards import DashboardService
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from memory import MemoryBackground, memory_adapters
from test_api_support import Overrides, Seen

WEB = {"kind": "user", "name": "web"}
AGENT = {"kind": "external_agent", "name": "claude-code"}


def widget_in(store: MemoryStore, project_id: str, title: str = "Coverage") -> Widget:
    widget = Widget(
        id=uuid7(),
        project_id=UUID(project_id),
        operator_id="op",
        type="value",
        title=title,
        created_by=factories.AGENT,
        created_at=factories.NOW,
    )
    store.widgets[widget.id] = widget
    return widget


# REST


@pytest.fixture
def overrides() -> Overrides:
    return Overrides()


@pytest.fixture
def client(unreachable_settings: Settings, overrides: Overrides) -> Iterator[TestClient]:
    with TestClient(create_app(unreachable_settings, *memory_adapters(), overrides)) as client:
        yield client


def store(client: TestClient) -> MemoryStore:
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    return client.portal.call(container.get, MemoryStore)


def published(client: TestClient) -> list[Any]:
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    return client.portal.call(container.get, MemoryEventBus).published


def send(client: TestClient, method: str, path: str, body: Any = None, ok: int = 200) -> Any:
    response = client.request(method, f"/api{path}", json=body)
    assert response.status_code == ok, response.text
    return response.json()


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return send(client, "POST", "/projects", {"name": "Wellbeing"}, 201)


@pytest.fixture
def dashboard(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return send(client, "POST", f"/projects/{project['id']}/dashboards", {"name": "Overview"}, 201)


def test_a_dashboard_is_created_listed_and_read(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    assert dashboard["name"] == "Overview"
    assert dashboard["revision"] == 1
    assert dashboard["current_version_id"] is None
    assert send(client, "GET", f"/projects/{project['id']}/dashboards") == [dashboard]
    assert send(client, "GET", f"/dashboards/{dashboard['id']}") == {
        "dashboard": dashboard,
        "version": None,
    }


def test_unknown_records_are_not_found(client: TestClient, dashboard: dict[str, Any]) -> None:
    missing = uuid7()
    assert client.get(f"/api/projects/{missing}/dashboards").status_code == 404
    assert client.post(f"/api/projects/{missing}/dashboards", json={"name": "x"}).status_code == 404
    assert client.get(f"/api/dashboards/{missing}").status_code == 404
    assert client.get(f"/api/dashboards/{missing}/versions").status_code == 404
    assert client.get(f"/api/dashboard-versions/{missing}").status_code == 404
    assert client.post(f"/api/dashboards/{missing}/runs").status_code == 404
    pin = {"widget_id": str(uuid7()), "slot": "a", "expected_revision": 1}
    assert client.post(f"/api/dashboards/{dashboard['id']}/pins", json=pin).status_code == 404


@pytest.mark.parametrize("body", [{}, {"name": 3}, {"name": "x", "extra": 1}])
def test_malformed_bodies_are_rejected(
    client: TestClient, project: dict[str, Any], body: dict[str, Any]
) -> None:
    assert client.post(f"/api/projects/{project['id']}/dashboards", json=body).status_code == 422


def test_a_blank_name_is_invalid(client: TestClient, project: dict[str, Any]) -> None:
    response = client.post(f"/api/projects/{project['id']}/dashboards", json={"name": " "})
    assert response.status_code == 422
    assert "name" in response.json()["detail"]


def test_pinning_adds_a_version_and_answers_with_the_new_state(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    widget = widget_in(store(client), project["id"])

    pinned = send(
        client,
        "POST",
        f"/dashboards/{dashboard['id']}/pins",
        {"widget_id": str(widget.id), "slot": "coverage", "expected_revision": 1},
        201,
    )

    assert pinned["dashboard"]["revision"] == 2
    assert pinned["dashboard"]["current_version_id"] == pinned["version"]["id"]
    assert pinned["version"]["number"] == 1
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
    # The dashboard shows its own copy, made by whoever pinned.
    copy = send(client, "GET", f"/widgets/{copy_id}")
    assert copy_id != str(widget.id)
    assert (copy["copied_from"], copy["session_id"], copy["created_by"]) == (
        str(widget.id),
        None,
        WEB,
    )
    assert (copy["operator_id"], copy["type"], copy["title"]) == (
        widget.operator_id,
        widget.type,
        widget.title,
    )
    assert send(client, "GET", f"/widgets/{widget.id}")["copied_from"] is None
    assert send(client, "GET", f"/dashboards/{dashboard['id']}") == pinned
    assert send(client, "GET", f"/dashboards/{dashboard['id']}/versions") == [pinned["version"]]
    assert (
        send(client, "GET", f"/dashboard-versions/{pinned['version']['id']}") == pinned["version"]
    )


def test_a_stale_pin_conflicts_with_both_revisions(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    widget = widget_in(store(client), project["id"])
    pin = {"widget_id": str(widget.id), "slot": "a", "expected_revision": 1}
    send(client, "POST", f"/dashboards/{dashboard['id']}/pins", pin, 201)

    response = client.post(f"/api/dashboards/{dashboard['id']}/pins", json=pin)

    assert response.status_code == 409
    body = response.json()
    assert (body["expected_revision"], body["revision"]) == (1, 2)
    assert len(send(client, "GET", f"/dashboards/{dashboard['id']}/versions")) == 1


def test_a_widget_of_another_project_cannot_be_pinned(
    client: TestClient, dashboard: dict[str, Any]
) -> None:
    foreign = widget_in(store(client), str(uuid7()))
    response = client.post(
        f"/api/dashboards/{dashboard['id']}/pins",
        json={"widget_id": str(foreign.id), "slot": "a", "expected_revision": 1},
    )
    assert response.status_code == 422


def test_the_slots_are_replaced_with_defaults_filled_in(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    widget = widget_in(store(client), project["id"])

    edited = send(
        client,
        "PUT",
        f"/dashboards/{dashboard['id']}/slots",
        {
            "slots": [
                {"name": "headline", "widget_id": str(widget.id), "layout": {"w": 12}},
                {"name": "notes", "description": "Anything on method"},
            ],
            "expected_revision": 1,
        },
    )

    first, second = edited["version"]["slots"]
    assert first["layout"] == {"x": 0, "y": 0, "w": 12, "h": 4}
    assert second["layout"] == {"x": 0, "y": 4, "w": 6, "h": 4}
    assert second["widget_id"] is None
    assert edited["dashboard"]["revision"] == 2


def test_a_bad_layout_is_unprocessable(client: TestClient, dashboard: dict[str, Any]) -> None:
    response = client.put(
        f"/api/dashboards/{dashboard['id']}/slots",
        json={"slots": [{"name": "a", "layout": {"x": 9, "w": 6}}], "expected_revision": 1},
    )
    assert response.status_code == 422
    assert "grid" in response.json()["detail"]


def test_an_edit_needs_a_revision(client: TestClient, dashboard: dict[str, Any]) -> None:
    assert (
        client.put(f"/api/dashboards/{dashboard['id']}/slots", json={"slots": []}).status_code
        == 422
    )


def test_the_default_time_range_is_set_and_conflicts_when_stale(
    client: TestClient, dashboard: dict[str, Any]
) -> None:
    changed = send(
        client,
        "PATCH",
        f"/dashboards/{dashboard['id']}",
        {
            "default_time_range": {"start": "2020-01-01", "end": "2024-12-31"},
            "expected_revision": 1,
        },
    )
    assert changed["dashboard"]["default_time_range"] == {
        "start": "2020-01-01",
        "end": "2024-12-31",
    }
    assert changed["dashboard"]["revision"] == 2

    stale = client.patch(
        f"/api/dashboards/{dashboard['id']}",
        json={"default_time_range": {}, "expected_revision": 1},
    )
    assert stale.status_code == 409


def test_a_run_for_a_dashboard_uses_its_range_unless_one_is_given(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
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
    assert default["bindings"] == {}
    # Each view is its own run, readable like any other.
    assert send(client, "GET", f"/runs/{given['id']}") == given


def test_changes_are_announced_on_the_live_stream(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    widget = widget_in(store(client), project["id"])
    pinned = send(
        client,
        "POST",
        f"/dashboards/{dashboard['id']}/pins",
        {"widget_id": str(widget.id), "slot": "a", "expected_revision": 1},
        201,
    )

    changes = [e for e in published(client) if e.type is EventType.DASHBOARD_CHANGED]
    assert [e.payload for e in changes] == [
        {"dashboard_id": dashboard["id"], "version_id": None},
        {"dashboard_id": dashboard["id"], "version_id": pinned["version"]["id"]},
    ]


def test_a_dashboard_has_one_agent_session(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    path = f"/api/dashboards/{dashboard['id']}/agent-session"
    # Sessions that do not both come from and show the dashboard are not its panel's.
    started_here = send(
        client,
        "POST",
        f"/projects/{project['id']}/sessions",
        {"title": "Explore", "origin_dashboard_id": dashboard["id"]},
        201,
    )

    created = client.post(path)
    found = client.post(path)

    assert created.status_code == 201
    assert found.status_code == 200
    session = created.json()
    assert found.json() == session
    assert session["id"] != started_here["id"]
    assert session["title"] == f"{dashboard['name']} (agent)"
    assert session["origin_dashboard_id"] == session["panel_dashboard_id"] == dashboard["id"]
    assert session["project_id"] == project["id"]
    created_events = [e for e in published(client) if e.type == EventType.SESSION_CREATED]
    assert created_events[-1].payload == {"session_id": session["id"]}


def test_the_newest_panel_session_is_the_agent_session(
    client: TestClient, project: dict[str, Any], dashboard: dict[str, Any]
) -> None:
    older = send(client, "POST", f"/dashboards/{dashboard['id']}/agent-session", None, 201)
    newer = send(
        client,
        "POST",
        f"/projects/{project['id']}/sessions",
        {"title": "Again", "origin_dashboard_id": dashboard["id"]},
        201,
    )
    send(
        client,
        "PATCH",
        f"/sessions/{newer['id']}",
        {"expected_revision": 1, "panel_dashboard_id": dashboard["id"]},
    )

    found = send(client, "POST", f"/dashboards/{dashboard['id']}/agent-session")

    assert found["id"] == newer["id"] != older["id"]


def test_an_unknown_dashboard_has_no_agent_session(client: TestClient) -> None:
    assert client.post(f"/api/dashboards/{uuid7()}/agent-session").status_code == 404


# MCP


@pytest.fixture
async def seen(unreachable_settings: Settings) -> AsyncIterator[Seen]:
    overrides = Overrides()
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), overrides
    )
    try:
        yield Seen(container, overrides)
    finally:
        await container.close()


@pytest.fixture
async def agent(seen: Seen) -> AsyncIterator[Client]:
    info = Implementation(name="claude-code", version="2.0")
    async with Client(create_mcp(seen.container), client_info=info) as client:
        yield client


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


async def make_widget(seen: Seen, project_id: str) -> Widget:
    return widget_in(await seen.container.get(MemoryStore), project_id)


@pytest.mark.anyio
async def test_the_dashboard_tools_are_served_and_documented(agent: Client) -> None:
    tools = {tool.name: tool for tool in await agent.list_tools()}
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
    injected = {"service", "sessions"}
    for name in expected:
        assert not set(tools[name].input_schema["properties"]) & injected, name


@pytest.mark.anyio
async def test_an_agent_creates_a_dashboard_and_pins_a_widget(agent: Client, seen: Seen) -> None:
    project = await call(agent, "create_project", name="Wellbeing")
    created = await call(agent, "create_dashboard", project_id=project["id"], name="Overview")
    assert created["version"] is None
    assert created["url"] == f"/projects/{project['id']}/dashboards/{created['dashboard']['id']}"
    assert await call(agent, "list_dashboards", project_id=project["id"]) == [created["dashboard"]]

    widget = await make_widget(seen, project["id"])
    pinned = await call(
        agent,
        "pin_widget",
        dashboard_id=created["dashboard"]["id"],
        widget_id=str(widget.id),
        slot="coverage",
        expected_revision=created["dashboard"]["revision"],
    )

    assert pinned["dashboard"]["revision"] == 2
    assert pinned["version"]["created_by"] == AGENT
    assert [s["name"] for s in pinned["version"]["slots"]] == ["coverage"]
    copy = (await seen.container.get(MemoryStore)).widgets[
        UUID(pinned["version"]["slots"][0]["widget_id"])
    ]
    assert (copy.copied_from, copy.session_id, copy.created_by.model_dump()) == (
        widget.id,
        None,
        AGENT,
    )
    assert await call(agent, "get_dashboard", dashboard_id=created["dashboard"]["id"]) == pinned
    versions = await call(agent, "list_dashboard_versions", dashboard_id=created["dashboard"]["id"])
    assert [v["number"] for v in versions] == [1]


@pytest.mark.anyio
async def test_a_stale_write_is_a_tool_error_naming_both_revisions(
    agent: Client, seen: Seen
) -> None:
    project = await call(agent, "create_project", name="Wellbeing")
    created = await call(agent, "create_dashboard", project_id=project["id"], name="Overview")
    widget = await make_widget(seen, project["id"])
    pin = {
        "dashboard_id": created["dashboard"]["id"],
        "widget_id": str(widget.id),
        "slot": "a",
        "expected_revision": 1,
    }
    await call(agent, "pin_widget", **pin)

    with pytest.raises(ToolError, match="revision 2.*expected revision 1"):
        await call(agent, "pin_widget", **pin)


@pytest.mark.anyio
async def test_the_slots_are_edited_over_mcp(agent: Client) -> None:
    project = await call(agent, "create_project", name="Wellbeing")
    created = await call(agent, "create_dashboard", project_id=project["id"], name="Overview")

    edited = await call(
        agent,
        "edit_dashboard",
        dashboard_id=created["dashboard"]["id"],
        expected_revision=1,
        slots=[{"name": "a", "layout": {"w": 4}}, {"name": "b"}],
    )

    layouts = [slot["layout"] for slot in edited["version"]["slots"]]
    assert layouts == [{"x": 0, "y": 0, "w": 4, "h": 4}, {"x": 4, "y": 0, "w": 6, "h": 4}]
    with pytest.raises(ToolError, match="unique"):
        await call(
            agent,
            "edit_dashboard",
            dashboard_id=created["dashboard"]["id"],
            expected_revision=2,
            slots=[{"name": "a"}, {"name": "a"}],
        )


@pytest.mark.anyio
async def test_the_time_range_is_set_from_iso_dates(agent: Client) -> None:
    project = await call(agent, "create_project", name="Wellbeing")
    created = await call(agent, "create_dashboard", project_id=project["id"], name="Overview")

    changed = await call(
        agent,
        "set_dashboard_time_range",
        dashboard_id=created["dashboard"]["id"],
        expected_revision=1,
        start="2020-01-01",
        end="2024-12-31",
    )
    assert changed["default_time_range"] == {"start": "2020-01-01", "end": "2024-12-31"}
    assert changed["revision"] == 2

    with pytest.raises(ToolError, match="ends before"):
        await call(
            agent,
            "set_dashboard_time_range",
            dashboard_id=created["dashboard"]["id"],
            expected_revision=2,
            start="2024-01-01",
            end="2020-01-01",
        )


@pytest.mark.anyio
async def test_a_dashboard_is_shown_in_a_session_and_the_panel_cleared(agent: Client) -> None:
    project = await call(agent, "create_project", name="Wellbeing")
    created = await call(agent, "create_dashboard", project_id=project["id"], name="Overview")
    session = await call(agent, "create_session", project_id=project["id"], title="Look")

    shown = await call(
        agent,
        "show_dashboard_in_session",
        session_id=session["id"],
        dashboard_id=created["dashboard"]["id"],
        expected_revision=session["revision"],
    )
    assert shown["session"]["panel_dashboard_id"] == created["dashboard"]["id"]
    assert shown["url"] == f"/projects/{project['id']}/sessions/{session['id']}"

    cleared = await call(
        agent,
        "show_dashboard_in_session",
        session_id=session["id"],
        expected_revision=shown["session"]["revision"],
    )
    assert cleared["session"]["panel_dashboard_id"] is None

    with pytest.raises(ToolError, match="revision"):
        await call(
            agent,
            "show_dashboard_in_session",
            session_id=session["id"],
            expected_revision=session["revision"],
        )


@pytest.mark.anyio
async def test_a_dashboard_of_another_project_cannot_be_shown_in_a_session(
    agent: Client,
) -> None:
    here = await call(agent, "create_project", name="Here")
    there = await call(agent, "create_project", name="There")
    foreign = await call(agent, "create_dashboard", project_id=there["id"], name="Overview")
    session = await call(agent, "create_session", project_id=here["id"], title="Look")

    with pytest.raises(ToolError, match="another project"):
        await call(
            agent,
            "show_dashboard_in_session",
            session_id=session["id"],
            dashboard_id=foreign["dashboard"]["id"],
            expected_revision=1,
        )


# PostgreSQL: what the memory adapters cannot show


@pytest.mark.anyio
async def test_versions_and_the_pointer_commit_together_and_a_conflict_rolls_back(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    container = create_container(settings, MemoryBackground())
    try:
        project = factories.project()
        async with container() as request:
            await (await request.get(ProjectRepository)).add(project)
            # The database keeps a widget's operator, so it comes first.
            operator = factories.operator(project.id)
            await (await request.get(OperatorRepository)).add(operator)
            widget = Widget(
                id=uuid7(),
                project_id=project.id,
                operator_id=operator.id,
                type="value",
                title="Coverage",
                created_by=factories.AGENT,
                created_at=factories.NOW,
            )
            await (await request.get(WidgetRepository)).add(widget)

        async with container() as request:
            service = await request.get(DashboardService)
            dashboard = await service.create(project.id, "Overview", factories.AGENT)
        async with container() as request:
            service = await request.get(DashboardService)
            first = await service.pin_widget(dashboard.id, widget.id, "a", 1, factories.AGENT)
        # A stale writer is refused and leaves no version behind.
        with pytest.raises(Conflict):
            async with container() as request:
                service = await request.get(DashboardService)
                await service.pin_widget(dashboard.id, widget.id, "b", 1, factories.AGENT)
        async with container() as request:
            service = await request.get(DashboardService)
            second = await service.pin_widget(dashboard.id, widget.id, "b", 2, factories.AGENT)
            stored = await service.get(dashboard.id)
            versions = await service.versions(dashboard.id)
            current = await service.current(dashboard.id)

        assert (first.number, second.number) == (1, 2)
        assert [v.id for v in versions] == [first.id, second.id]
        assert current == second
        assert (stored.current_version_id, stored.revision) == (second.id, 3)
        assert [(s.name, s.layout) for s in current.slots] == [
            ("a", {"x": 0, "y": 0, "w": 6, "h": 4}),
            ("b", {"x": 6, "y": 0, "w": 6, "h": 4}),
        ]
    finally:
        await container.close()
