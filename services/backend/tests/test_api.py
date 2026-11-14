"""The API surface: the REST routes of projects, sources, sessions, operators, runs and
widgets, the MCP tools an outside agent uses for the same, health, the built widget
bundles, and the composition root. The pipeline, run and source services are fakes
(api_support.py); one app and one MCP client serve the whole module."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

from ada.adapters.db.workspace_repositories import SqlProjectRepository
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.composition import create_container, providers
from ada.composition import unbuilt as unbuilt_module
from ada.composition.unbuilt import Unbuilt
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.errors import Unavailable
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.repositories import ProjectRepository
from ada.core.services.dashboards.service import Dashboards
from ada.core.services.pipelines.runs import Runs
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.runs import RunService
from ada.discovery import modules
from ada.entrypoints.mcp import actor
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.mcp.sessions import SESSIONLESS
from api_support import (
    Overrides,
    Seen,
    call,
    dispatcher,
    events,
    mcp_client,
    new_project,
    send,
    serve,
    store,
)
from conftest import UNREACHABLE_HEALTH
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio

WEB = {"kind": "user", "name": "web"}
AGENT = {"kind": "external_agent", "name": "claude-code"}


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return new_project(client)


@pytest.fixture
def source(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    body = {
        "name": "Sotkanet",
        "access_kind": "url",
        "address": "https://example.test/data.csv",
        "format": "csv",
    }
    return send(client, "POST", f"/projects/{project['id']}/sources", body, 201)


@pytest.fixture
def source_operator(
    client: TestClient, project: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    body = {"kind": "source", "data_source_id": source["id"]}
    return send(client, "POST", f"/projects/{project['id']}/operators", body, 201)


@pytest.fixture
def session(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "Look"}, 201)


# REST


def test_a_project_is_renamed_from_its_current_revision_only(client: TestClient) -> None:
    created = new_project(client, "  Wellbeing ")
    path = f"/api/projects/{created['id']}"

    renamed = client.patch(path, json={"name": "Health", "expected_revision": 1})
    stale = client.patch(path, json={"name": "Other", "expected_revision": 1})

    assert (created["name"], created["revision"]) == ("Wellbeing", 1)
    assert created["id"] in [p["id"] for p in send(client, "GET", "/projects")]
    assert (renamed.json()["name"], renamed.json()["revision"]) == ("Health", 2)
    assert stale.status_code == 409
    assert stale.json() == {"detail": stale.json()["detail"], "expected_revision": 1, "revision": 2}
    assert send(client, "GET", f"/projects/{created['id']}")["name"] == "Health"


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("POST", "/projects", {"name": "   "}, 422),
        ("GET", "/projects/not-an-id", None, 422),
        ("PATCH", "/projects/{project}", {"name": "x"}, 422),
        ("POST", "/projects/{project}/operators", {"kind": "agent", "prompt": "x"}, 422),
        ("GET", "/runs/{run}/operators/op_x/rows?limit=0", None, 422),
        ("GET", "/operators/op_missing/lineage", None, 404),
    ],
)
def test_requests_that_cannot_work_are_refused(
    client: TestClient,
    project: dict[str, Any],
    method: str,
    path: str,
    body: Any,
    status: int,
) -> None:
    run = send(client, "POST", f"/projects/{project['id']}/runs", None, 201)
    url = "/api" + path.format(project=project["id"], run=run["id"])
    assert client.request(method, url, json=body).status_code == status


def test_a_source_is_fetched_again_at_once_only_when_what_is_fetched_changed(
    client: TestClient, source: dict[str, Any]
) -> None:
    path = f"/api/sources/{source['id']}"

    renamed = client.patch(path, json={"expected_revision": 1, "name": "Renamed"})
    reshaped = client.patch(path, json={"expected_revision": 2, "options": {"path": "rows"}})
    stale = client.patch(path, json={"expected_revision": 1, "name": "B"})

    assert renamed.status_code == reshaped.status_code == 200
    # Left out means unchanged.
    assert reshaped.json()["address"] == source["address"]
    assert stale.status_code == 409
    refreshes = [(str(i), force) for i, force in dispatcher(client).refreshes]
    assert [r for r in refreshes if r[0] == source["id"]] == [(source["id"], True)]


def test_a_refresh_is_queued_or_answered_503_when_the_queue_is_down(
    client: TestClient, source: dict[str, Any]
) -> None:
    queued = client.post(f"/api/sources/{source['id']}/refresh", json={"force": True})
    recording = dispatcher(client)

    async def unreachable(data_source_id: UUID, force: bool = False) -> None:
        raise Unavailable("The task queue could not be reached: connection refused")

    with patch.object(recording, "refresh_source", unreachable):
        down = client.post(f"/api/sources/{source['id']}/refresh")

    assert (queued.status_code, queued.json()) == (
        202,
        {"data_source_id": source["id"], "force": True},
    )
    assert (UUID(source["id"]), True) in recording.refreshes
    assert down.status_code == 503
    assert down.json() == {"detail": "The task queue could not be reached: connection refused"}


def test_a_message_is_recorded_as_the_web_user_and_announced(
    client: TestClient, project: dict[str, Any], session: dict[str, Any]
) -> None:
    for text in ("What changed?", "And why?"):
        posted = send(client, "POST", f"/sessions/{session['id']}/messages", {"text": text}, 201)

    # No models file in the tests, so no agent answers.
    assert posted["turn"] is None
    entries = send(client, "GET", f"/sessions/{session['id']}/entries")
    assert [(e["kind"], e["text"], e["actor"]) for e in entries] == [
        ("message", "What changed?", WEB),
        ("message", "And why?", WEB),
    ]
    added = [e for e in events(client, project["id"]) if e.type == "session.entry_added"]
    assert added[-1].payload == {"session_id": session["id"], "entry_id": posted["entry"]["id"]}


def test_a_session_attaches_things_of_its_project_once_and_detaches_them(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    path = f"/sessions/{session['id']}/attachments"
    own = send(client, "POST", f"/projects/{project['id']}/dashboards", {"name": "Own"}, 201)
    other = new_project(client, "Other")
    foreign = send(client, "POST", f"/projects/{other['id']}/dashboards", {"name": "X"}, 201)
    url = "https://stat.fi/til/index.html"

    dashboard = send(client, "POST", path, {"kind": "dashboard", "ref": own["id"]}, 201)
    again = send(client, "POST", path, {"kind": "dashboard", "ref": own["id"]}, 201)
    pipeline = send(client, "POST", path, {"kind": "operator", "ref": source_operator["id"]}, 201)
    page = send(client, "POST", path, {"kind": "web_page", "ref": url}, 201)
    refused = [
        client.post(f"/api{path}", json=body).status_code
        for body in (
            {"kind": "dashboard", "ref": foreign["id"]},
            {"kind": "dashboard", "ref": str(uuid7())},
            {"kind": "web_page", "ref": "ftp://stat.fi/file.csv"},
            {"kind": "session", "ref": session["id"]},
            {"kind": "chart", "ref": "x"},
        )
    ]
    detached = client.delete(f"/api{path}/{pipeline['id']}")
    gone = client.delete(f"/api{path}/{pipeline['id']}")
    # Renaming is what is left of changing a session.
    changed = f"/api/sessions/{session['id']}"
    renamed = client.patch(changed, json={"title": "New", "expected_revision": 1})
    shown = {"title": "New", "expected_revision": 2, "panel_dashboard_id": own["id"]}
    panel = client.patch(changed, json=shown)

    assert (dashboard["kind"], dashboard["title"], dashboard["actor"]) == ("dashboard", "Own", WEB)
    assert again == dashboard
    assert (pipeline["ref"], pipeline["title"]) == (source_operator["id"], "Sotkanet")
    assert (page["ref"], page["title"]) == (url, "stat.fi")
    assert refused == [422, 404, 422, 422, 422]
    assert (detached.status_code, gone.status_code) == (204, 404)
    assert send(client, "GET", path) == [dashboard, page]
    assert client.get(f"/api/sessions/{uuid7()}/attachments").status_code == 404
    changes = [e for e in events(client, project["id"]) if e.type.startswith("session.attach")]
    assert [(e.type, e.payload["attachment_id"]) for e in changes] == [
        ("session.attachment_added", dashboard["id"]),
        ("session.attachment_added", pipeline["id"]),
        ("session.attachment_added", page["id"]),
        ("session.attachment_removed", pipeline["id"]),
    ]
    assert changes[0].payload == {
        "session_id": session["id"],
        "attachment_id": dashboard["id"],
        "attachment": dashboard,
    }
    assert renamed.json()["title"] == "New" and "panel_dashboard_id" not in renamed.json()
    assert panel.status_code == 422


def test_operators_are_added_through_the_pipeline_service_and_recorded_in_the_session(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    transform = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {
            "kind": "transform",
            "sql": "SELECT region, value FROM input_0",
            "inputs": [source_operator["id"]],
            "session_id": session["id"],
            "note": "Only what we need",
        },
        201,
    )
    invalid = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "transform", "sql": "DROP TABLE x", "inputs": []},
    )

    assert source_operator["created_by"] == WEB
    lineage = send(client, "GET", f"/operators/{transform['id']}/lineage")
    assert [operator["id"] for operator in lineage] == [source_operator["id"], transform["id"]]
    [entry] = send(client, "GET", f"/sessions/{session['id']}/entries")
    assert (entry["kind"], entry["ref"], entry["text"]) == (
        "operator",
        transform["id"],
        "Only what we need",
    )
    assert (invalid.status_code, "Not a query" in invalid.json()["detail"]) == (422, True)


def test_a_widget_carries_no_data_and_reads_it_in_a_run(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    path = f"/api/projects/{project['id']}/widgets"
    body = {"operator_id": source_operator["id"], "type": "table", "title": "Regions"}
    with_rows = client.post(path, json={**body, "rows": [["a", 1]]})
    widget = send(client, "POST", path[4:], {**body, "session_id": session["id"]}, 201)
    scenario = send(
        client, "POST", f"/projects/{project['id']}/runs", {"bindings": {"rate": "op_x"}}, 201
    )
    other = new_project(client, "Other")
    foreign_run = send(client, "POST", f"/projects/{other['id']}/runs", None, 201)

    fresh = send(client, "GET", f"/widgets/{widget['id']}/data")
    in_scenario = send(
        client, "GET", f"/widgets/{widget['id']}/data?run_id={scenario['id']}&limit=1"
    )
    foreign = client.get(f"/api/widgets/{widget['id']}/data?run_id={foreign_run['id']}")

    assert with_rows.status_code == 422
    assert send(client, "GET", f"/sessions/{session['id']}/widgets") == [widget]
    assert [e.type for e in events(client, project["id"])][-2:] == [
        "widget.created",
        "session.entry_added",
    ]
    # Without a run, one is started for the latest data; the columns' meaning comes along.
    assert (fresh["is_scenario"], fresh["is_stale"]) == (False, False)
    assert fresh["output"] == source_operator["output"]
    assert send(client, "GET", f"/runs/{fresh['run_id']}")["started_by"]["kind"] == "system"
    assert (in_scenario["is_scenario"], in_scenario["rows"], in_scenario["truncated"]) == (
        True,
        [["north", 1.5]],
        True,
    )
    assert foreign.status_code == 422


def test_a_file_is_uploaded_once_per_content(client: TestClient, project: dict[str, Any]) -> None:
    path = f"/api/projects/{project['id']}/files?filename=Handout.PDF"
    first = client.post(
        path, content=b"%PDF-1.7 handout", headers={"Content-Type": "application/pdf"}
    )
    again = client.post(path, content=b"%PDF-1.7 handout")
    empty = client.post(path, content=b"")

    assert first.status_code == 201
    assert first.json() == again.json()
    assert first.json()["address"].startswith(f"upload://{project['id']}/")
    assert first.json()["address"].endswith(".pdf") and first.json()["size"] == 16
    assert empty.status_code == 422


def test_a_widget_is_changed_in_place_and_its_spec_checked(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    path = f"/projects/{project['id']}/widgets"
    body = {"operator_id": source_operator["id"], "type": "table", "title": "Regions"}
    widget = send(client, "POST", path, body, 201)

    changed = send(
        client,
        "PATCH",
        f"/widgets/{widget['id']}",
        {"title": "Regions by name", "spec": {"labels": {"region": "Region"}}},
    )
    refused = client.patch(
        f"/api/widgets/{widget['id']}", json={"spec": {"labels": {"nope": "Nope"}}}
    )

    assert (changed["title"], changed["spec"], changed["note"]) == (
        "Regions by name",
        {"labels": {"region": "Region"}},
        "",
    )
    assert send(client, "GET", f"/widgets/{widget['id']}") == changed
    assert refused.status_code == 422 and "nope" in refused.json()["detail"]
    assert [e.type for e in events(client, project["id"])][-1] == "widget.updated"


def test_a_widget_reads_further_inputs_by_name_in_the_same_run(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    total = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {
            "kind": "transform",
            "sql": "SELECT sum(value) AS total FROM input_0",
            "inputs": [source_operator["id"]],
        },
        201,
    )
    path = f"/projects/{project['id']}/widgets"
    body = {"operator_id": source_operator["id"], "type": "table", "title": "Regions"}
    widget = send(client, "POST", path, {**body, "inputs": {"total": total["id"]}}, 201)
    other = new_project(client, "Other")
    foreign = send(
        client,
        "POST",
        f"/projects/{other['id']}/operators",
        {"kind": "transform", "sql": "SELECT 1 AS one", "inputs": []},
        201,
    )
    refused = [
        client.post(f"/api{path}", json={**body, "inputs": inputs}).status_code
        for inputs in ({"main": total["id"]}, {"Total": total["id"]}, {"x": foreign["id"]})
    ]

    main = send(client, "GET", f"/widgets/{widget['id']}/data")
    extra = send(client, "GET", f"/widgets/{widget['id']}/data?run_id={main['run_id']}&input=total")
    unknown = client.get(f"/api/widgets/{widget['id']}/data?input=nope")
    cleared = send(client, "PATCH", f"/widgets/{widget['id']}", {"inputs": {}})

    assert widget["inputs"] == {"total": total["id"]}
    assert refused == [422, 422, 422]
    assert (main["input"], extra["input"], extra["run_id"]) == ("main", "total", main["run_id"])
    assert unknown.status_code == 422 and "main, total" in unknown.json()["detail"]
    assert cleared["inputs"] == {}


def test_widget_data_is_stale_while_a_source_upstream_failed_its_refresh(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    transform = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {"kind": "transform", "sql": "SELECT * FROM input_0", "inputs": [source_operator["id"]]},
        201,
    )
    widget = send(
        client,
        "POST",
        f"/projects/{project['id']}/widgets",
        {"operator_id": transform["id"], "type": "table", "title": "t"},
        201,
    )
    assert send(client, "GET", f"/widgets/{widget['id']}/data")["is_stale"] is False

    # What the worker's failed refresh leaves on the source.
    memory = store(client)
    failed = memory.data_sources[UUID(source["id"])]
    memory.data_sources[failed.id] = failed.model_copy(update={"last_error": "HTTP 503"})

    assert send(client, "GET", f"/widgets/{widget['id']}/data")["is_stale"] is True


def test_the_pipelines_route_lists_what_nothing_builds_on(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    transform = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {"kind": "transform", "sql": "SELECT * FROM input_0", "inputs": [source_operator["id"]]},
        201,
    )

    assert send(client, "GET", f"/projects/{project['id']}/pipelines") == [
        {
            "operator_id": transform["id"],
            "name": "SELECT * FROM input_0",
            "kind": "transform",
            "sources": [{"data_source_id": source["id"], "name": "Sotkanet"}],
            "output": transform["output"],
            "created_at": transform["created_at"],
        }
    ]


def test_the_openapi_schema_lists_every_route_of_the_contract(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    expected = {
        ("get", "/api/projects"),
        ("patch", "/api/projects/{project_id}"),
        ("post", "/api/projects/{project_id}/sources"),
        ("patch", "/api/sources/{source_id}"),
        ("post", "/api/sources/{source_id}/refresh"),
        ("post", "/api/projects/{project_id}/sessions"),
        ("patch", "/api/sessions/{session_id}"),
        ("post", "/api/sessions/{session_id}/messages"),
        ("post", "/api/projects/{project_id}/operators"),
        ("get", "/api/operators/{operator_id}/lineage"),
        ("post", "/api/projects/{project_id}/runs"),
        ("get", "/api/runs/{run_id}/operators/{operator_id}/rows"),
        ("get", "/api/snapshots/{snapshot_id}"),
        ("post", "/api/projects/{project_id}/widgets"),
        ("get", "/api/widgets/{widget_id}/data"),
        ("get", "/api/projects/{project_id}/pipelines"),
    }
    served = {(method, path) for path, methods in paths.items() for method in methods}
    assert expected <= served


def test_health_reports_unreachable_dependencies_and_liveness_ignores_them(
    client: TestClient,
) -> None:
    health = client.get("/api/health")
    live = client.get("/api/health/live")

    assert (health.status_code, health.json()) == (503, UNREACHABLE_HEALTH)
    assert (live.status_code, live.json()) == (200, {"status": "ok"})


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_the_mcp_endpoint_answers_initialize(client: TestClient, path: str) -> None:
    response = client.post(
        path,
        headers={"Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


# MCP


@pytest.fixture(scope="module")
async def agent(unreachable_settings: Settings) -> AsyncIterator[tuple[Client, Seen]]:
    async with mcp_client(unreachable_settings) as agent:
        yield agent


async def test_the_tools_are_verbs_documented_for_an_agent_without_injected_parameters(
    agent: tuple[Client, Seen],
) -> None:
    client, _ = agent
    tools = {tool.name: tool for tool in await client.list_tools()}
    verbs = {"list", "create", "register", "update", "refresh", "add", "get", "preview", "system"}
    verbs |= {"pin", "edit", "set", "show", "generate", "check", "build", "query", "search"}
    verbs |= {"read", "extract", "map", "watch", "unwatch", "delegate", "report"}
    verbs |= {"attach", "detach"}
    injected = {"service", "projects", "pipelines", "sessions", "widgets", "runs", "dispatcher"}
    injected |= {"exploration", "batches", "refreshes", "web", "research", "attachments"}

    for name, tool in tools.items():
        assert name.split("_")[0] in verbs, name
        assert tool.description and len(tool.description) > 40, name
        assert not set(tool.input_schema.get("properties", {})) & injected, name
    # Every tool works in a session, but those that find or make one, and the widget's own.
    for name, tool in tools.items():
        required = "session_id" in tool.input_schema.get("required", [])
        assert required is (name not in SESSIONLESS), name
    # What an agent makes in a session may say why; a widget carries no data.
    for name in ("add_source_operator", "add_transform", "create_widget"):
        assert "note" in tools[name].input_schema["properties"]
        assert "note" not in tools[name].input_schema["required"]
    assert set(tools["create_widget"].input_schema["properties"]) == {
        "operator_id",
        "type",
        "title",
        "spec",
        "session_id",
        "note",
        "inputs",
    }
    status = await client.call_tool("system_status")
    assert status.structured_content == UNREACHABLE_HEALTH


async def test_an_agent_builds_a_widget_in_a_session_and_is_recorded_as_itself(
    agent: tuple[Client, Seen],
) -> None:
    client, seen = agent
    project = await call(client, "create_project", name="Wellbeing")
    session = await call(client, "create_session", project_id=project["id"], title="Look")
    source = await call(
        client,
        "register_source",
        project_id=project["id"],
        session_id=session["id"],
        name="Statfin",
        address="https://example.test/api",
        access_kind="request",
        format="json",
        options={"method": "POST", "body": {"query": []}},
        freshness={"kind": "ttl", "ttl_seconds": 3600},
    )
    operator = await call(
        client,
        "add_source_operator",
        project_id=project["id"],
        data_source_id=source["id"],
        session_id=session["id"],
        note="Starting from the raw data",
    )
    transform = await call(
        client,
        "add_transform",
        project_id=project["id"],
        session_id=session["id"],
        sql="SELECT region, value FROM input_0",
        inputs=[operator["id"]],
        roles={"measures": [{"value": "value"}]},
    )
    preview = await call(
        client, "preview_operator", session_id=session["id"], operator_id=transform["id"], limit=1
    )
    created = await call(
        client,
        "create_widget",
        operator_id=transform["id"],
        type="table",
        title="Regions",
        session_id=session["id"],
        note="The regions side by side",
    )

    assert (source["access_kind"], source["freshness"]["ttl_seconds"]) == ("request", 3600)
    assert operator["created_by"] == AGENT
    assert transform["output"]["roles"]["measures"][0]["value"] == "value"
    assert (preview["rows"]["rows"], preview["rows"]["truncated"]) == ([["north", 1.5]], True)
    assert seen.results.reads[-1][1:] == (transform["id"], 1)
    widget = created["widget"]
    assert created["url"] == (
        f"/projects/{project['id']}/sessions/{session['id']}?widget={widget['id']}"
    )
    assert await call(client, "list_session_widgets", session_id=session["id"]) == [created]
    entries = await seen.entries(UUID(session["id"]))
    # Each call is recorded after it ran, so after the entry of what it made.
    assert [
        (e.kind, e.ref or (e.tool_call and e.tool_call.tool), e.actor.name) for e in entries
    ] == [
        ("tool_call", "register_source", "claude-code"),
        ("operator", operator["id"], "claude-code"),
        ("tool_call", "add_source_operator", "claude-code"),
        ("operator", transform["id"], "claude-code"),
        ("tool_call", "add_transform", "claude-code"),
        ("tool_call", "preview_operator", "claude-code"),
        ("widget", widget["id"], "claude-code"),
        ("tool_call", "create_widget", "claude-code"),
        ("tool_call", "list_session_widgets", "claude-code"),
    ]
    assert [e.type for e in await seen.events(project["id"])] == [
        "session.created",
        *["session.entry_added"] * 6,
        "widget.created",
        *["session.entry_added"] * 3,
    ]


async def test_tool_errors_say_what_is_wrong_and_change_nothing(
    agent: tuple[Client, Seen],
) -> None:
    client, seen = agent
    project = await call(client, "create_project", name="Wellbeing")
    here = (await call(client, "create_session", project_id=project["id"], title="Here"))["id"]
    source = await call(
        client,
        "register_source",
        project_id=project["id"],
        session_id=here,
        name="S",
        address="https://x.test",
    )
    other = await call(client, "create_project", name="Other")
    elsewhere = await call(client, "create_session", project_id=other["id"], title="Elsewhere")
    recording = await seen.dispatcher()

    with pytest.raises(ToolError, match="not found"):
        await call(client, "create_session", project_id=str(uuid7()), title="x")
    with pytest.raises(ToolError, match="needs a name"):
        await call(client, "create_project", name=" ")
    with pytest.raises(ToolError, match="revision"):
        await call(
            client,
            "update_source",
            session_id=here,
            source_id=source["id"],
            expected_revision=7,
            address="https://example.test/other.csv",
        )
    with pytest.raises(ToolError, match="another project"):
        await call(
            client,
            "add_source_operator",
            project_id=project["id"],
            data_source_id=source["id"],
            session_id=elsewhere["id"],
        )

    async def unreachable(data_source_id: UUID, force: bool = False) -> None:
        raise Unavailable("The task queue could not be reached: connection refused")

    with patch.object(recording, "refresh_source", unreachable):
        with pytest.raises(ToolError, match=r"could not be reached: .*try again later"):
            await call(client, "refresh_source", session_id=here, source_id=source["id"])
    assert UUID(source["id"]) not in [i for i, _ in recording.refreshes]


async def test_every_tool_call_needs_a_session_of_its_project(
    agent: tuple[Client, Seen],
) -> None:
    client, seen = agent
    project = await call(client, "create_project", name="Wellbeing")
    session = await call(client, "create_session", project_id=project["id"], title="Here")
    other = await call(client, "create_project", name="Other")

    with pytest.raises(ToolError, match="Pass `session_id`.*create_session"):
        await call(client, "list_sources", project_id=project["id"])
    with pytest.raises(ToolError, match="session .* not found"):
        await call(client, "list_sources", project_id=project["id"], session_id=str(uuid7()))
    with pytest.raises(ToolError, match="another project"):
        await call(
            client,
            "register_source",
            project_id=other["id"],
            session_id=session["id"],
            name="S",
            address="https://x.test",
        )

    # Refused before they ran: nothing was made, and the session shows none of them.
    assert await seen.entries(UUID(session["id"])) == []
    there = await call(client, "create_session", project_id=other["id"], title="There")
    assert await call(client, "list_sources", project_id=other["id"], session_id=there["id"]) == []


async def test_each_call_is_recorded_with_its_outcome_and_shortened_arguments(
    agent: tuple[Client, Seen],
) -> None:
    client, seen = agent
    project = await call(client, "create_project", name="Wellbeing")
    session = await call(client, "create_session", project_id=project["id"], title="Here")
    sql = "SELECT " + ", ".join(f"c{i}" for i in range(500)) + " FROM input_0"

    await call(
        client,
        "register_source",
        project_id=project["id"],
        session_id=session["id"],
        name="S" * 300,
        address="https://x.test",
        options={"rows_path": [str(i) for i in range(12)]},
    )
    with pytest.raises(ToolError, match="Not a query"):
        await call(
            client,
            "add_transform",
            project_id=project["id"],
            session_id=session["id"],
            sql="nope",
            inputs=[],
        )
    with pytest.raises(ToolError):
        await call(
            client,
            "add_transform",
            project_id=project["id"],
            session_id=session["id"],
            sql=sql,
            inputs=[str(uuid7())],
        )

    registered, refused, unknown = await seen.entries(UUID(session["id"]))
    assert all(
        e.kind == "tool_call" and e.actor.model_dump() == AGENT for e in (registered, refused)
    )
    assert registered.tool_call is not None and refused.tool_call is not None
    assert (registered.tool_call.status, registered.tool_call.error) == ("ok", None)
    arguments = registered.tool_call.arguments
    assert arguments["name"] == "S" * 200 + "…"
    assert arguments["options"]["rows_path"] == [*map(str, range(10)), "… 2 more"]
    assert (refused.tool_call.tool, refused.tool_call.status) == ("add_transform", "error")
    assert refused.tool_call.error == "Not a query: nope"
    assert refused.tool_call.duration_ms >= 0
    # SQL is what a person reads to follow the work: kept whole up to 2,000 characters.
    assert unknown.tool_call is not None and unknown.tool_call.arguments["sql"] == sql[:2000] + "…"
    entries_added = [e for e in await seen.events(project["id"]) if e.type == "session.entry_added"]
    assert [e.payload["entry_id"] for e in entries_added] == [
        str(e.id) for e in (registered, refused, unknown)
    ]


@pytest.mark.parametrize(
    "client_params",
    [
        None,
        SimpleNamespace(client_info=Implementation(name=" ", version="1")),
        SimpleNamespace(client_info=Implementation(name="fastmcp", version="3")),
    ],
)
def test_without_a_client_name_the_actor_has_none(client_params: object) -> None:
    # A library's default name says nothing about the agent, so it is not recorded either.
    context = SimpleNamespace(session=SimpleNamespace(client_params=client_params))
    with patch.object(actor, "get_context", return_value=context):
        assert actor.calling_agent() == Actor(kind=ActorKind.EXTERNAL_AGENT, name="")
    with patch.object(actor, "get_context", side_effect=RuntimeError("No active context")):
        assert actor.calling_agent().name == ""


# The built widgets: served to the frontend over REST, and to MCP hosts as MCP Apps


BUNDLE = "<!doctype html><title>Table</title>"


async def test_built_widgets_are_served_over_rest_and_as_mcp_app_resources(
    unreachable_settings: Settings, tmp_path: Path
) -> None:
    widgets = tmp_path / "widgets"
    widgets.mkdir()
    (widgets / "table.html").write_text(BUNDLE)
    (widgets / "any.html").write_text("<!doctype html><title>Widget</title>")
    (tmp_path / "secret.html").write_text("not a widget")
    settings = unreachable_settings.model_copy(update={"widgets_dir": widgets})
    container = create_container(settings, FastapiProvider(), *memory_adapters(), Overrides())
    try:
        async with Client(create_mcp(container, widgets)) as mcp:
            resources = {str(r.uri): r for r in await mcp.list_resources()}
            [content] = await mcp.read_resource("ui://ada/widgets/table.html")
            tools = {tool.name: tool for tool in await mcp.list_tools()}
    finally:
        await container.close()
    with serve(settings) as client:
        served = client.get("/api/widget-bundles/table.html")
        refused = [
            client.get(f"/api/widget-bundles/{name}").status_code
            for name in ("map.html", "..%2Fsecret.html", "Table.html")
        ]

    assert set(resources) == {"ui://ada/widgets/table.html", "ui://ada/widgets/any.html"}
    assert resources["ui://ada/widgets/table.html"].mime_type == "text/html;profile=mcp-app"
    assert getattr(content, "text", None) == BUNDLE
    meta: dict[str, Any] = tools["create_widget"].meta or {}
    assert meta["ui"]["resourceUri"] == "ui://ada/widgets/any.html"
    assert (served.status_code, served.text) == (200, BUNDLE)
    assert served.headers["content-type"].startswith("text/html")
    assert refused == [404, 404, 404]


# The composition root


async def test_the_container_binds_every_port_to_a_real_implementation(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, FastapiProvider(), MemoryBackground())
    try:
        assert isinstance(await container.get(AnalysisStore), DuckDbAnalysisStore)
        async with container() as request:
            # Resolving opens no connection yet, so this works with the database down.
            assert isinstance(await request.get(ProjectRepository), SqlProjectRepository)
            assert isinstance(await request.get(DashboardService), Dashboards)
            assert isinstance(await request.get(RunService), Runs)
    finally:
        await container.close()
    # The stand-in stays for ports a later wave adds; none may ship on it.
    standing_in = [
        factory.provides.type_hint
        for module in modules(providers)
        for factory in module.provider.factories
        if getattr(factory.source, "__module__", None) == unbuilt_module.__name__
    ]
    assert standing_in == []
    with pytest.raises(NotImplementedError, match="DashboardService"):
        Unbuilt(DashboardService).list(uuid7())
