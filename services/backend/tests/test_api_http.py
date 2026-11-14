"""The REST routes of projects, sources, sessions, operators, runs and widgets."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient

from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.config import Settings
from ada.core.models.dashboards import Dashboard
from ada.core.models.errors import Unavailable
from ada.core.models.events import Event
from ada.core.ports.tasks import TaskDispatcher
from ada.entrypoints.http.app import create_app
from factories import NOW
from memory import memory_adapters
from test_api_support import Overrides

WEB = {"kind": "user", "name": "web"}


@pytest.fixture
def overrides() -> Overrides:
    return Overrides()


@pytest.fixture
def client(unreachable_settings: Settings, overrides: Overrides) -> Iterator[TestClient]:
    with TestClient(create_app(unreachable_settings, *memory_adapters(), overrides)) as client:
        yield client


def resolve[T](client: TestClient, port: type[T]) -> T:
    """An application-scoped object of the app under test, e.g. the event bus."""
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    return client.portal.call(container.get, port)


def events(client: TestClient) -> list[Event]:
    return resolve(client, MemoryEventBus).published


def store(client: TestClient) -> MemoryStore:
    return resolve(client, MemoryStore)


def dispatcher(client: TestClient) -> RecordingTaskDispatcher:
    found = resolve(client, TaskDispatcher)
    assert isinstance(found, RecordingTaskDispatcher)
    return found


def post(client: TestClient, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(f"/api{path}", json=body or {})
    assert response.status_code in (200, 201, 202), response.text
    return response.json()


def get(client: TestClient, path: str) -> Any:
    response = client.get(f"/api{path}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return post(client, "/projects", {"name": "Wellbeing"})


@pytest.fixture
def source(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return post(
        client,
        f"/projects/{project['id']}/sources",
        {
            "name": "Sotkanet",
            "access_kind": "url",
            "address": "https://example.test/data.csv",
            "format": "csv",
        },
    )


@pytest.fixture
def source_operator(
    client: TestClient, project: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    return post(
        client,
        f"/projects/{project['id']}/operators",
        {"kind": "source", "data_source_id": source["id"]},
    )


@pytest.fixture
def session(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return post(client, f"/projects/{project['id']}/sessions", {"title": "First look"})


# Projects


def test_projects_are_created_listed_read_and_renamed(client: TestClient) -> None:
    assert get(client, "/projects") == []
    created = post(client, "/projects", {"name": "  Wellbeing "})
    assert created["name"] == "Wellbeing"
    assert created["revision"] == 1
    assert get(client, "/projects") == [created]
    assert get(client, f"/projects/{created['id']}") == created

    response = client.patch(
        f"/api/projects/{created['id']}", json={"name": "Health", "expected_revision": 1}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Health"
    assert response.json()["revision"] == 2


def test_renaming_a_project_from_a_stale_revision_conflicts(
    client: TestClient, project: dict[str, Any]
) -> None:
    client.patch(f"/api/projects/{project['id']}", json={"name": "A", "expected_revision": 1})
    response = client.patch(
        f"/api/projects/{project['id']}", json={"name": "B", "expected_revision": 1}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["expected_revision"] == 1
    assert body["revision"] == 2
    assert get(client, f"/projects/{project['id']}")["name"] == "A"


def test_unknown_project_is_not_found(client: TestClient) -> None:
    missing = uuid7()
    assert client.get(f"/api/projects/{missing}").status_code == 404
    assert client.get(f"/api/projects/{missing}/sources").status_code == 404
    assert client.get(f"/api/projects/{missing}/sessions").status_code == 404
    patch = client.patch(f"/api/projects/{missing}", json={"name": "x", "expected_revision": 1})
    assert patch.status_code == 404
    assert client.post(f"/api/projects/{missing}/sessions", json={"title": "x"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"name": 3}, {"name": "x", "expected_revision": "one"}])
def test_malformed_bodies_are_rejected(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/projects", json=body).status_code == 422


def test_a_blank_name_is_invalid(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "   "})
    assert response.status_code == 422
    assert "name" in response.json()["detail"]


def test_a_malformed_id_is_rejected(client: TestClient) -> None:
    assert client.get("/api/projects/not-an-id").status_code == 422


def test_renaming_needs_a_revision(client: TestClient, project: dict[str, Any]) -> None:
    assert client.patch(f"/api/projects/{project['id']}", json={"name": "x"}).status_code == 422


# Sources


def test_sources_are_registered_listed_read_and_updated(
    client: TestClient, project: dict[str, Any], source: dict[str, Any]
) -> None:
    assert source["project_id"] == project["id"]
    assert get(client, f"/projects/{project['id']}/sources") == [source]
    assert get(client, f"/sources/{source['id']}") == source

    response = client.patch(
        f"/api/sources/{source['id']}",
        json={"expected_revision": 1, "name": "Sotkanet 2", "options": {"path": "rows"}},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Sotkanet 2"
    assert updated["options"] == {"path": "rows"}
    # Left out means unchanged.
    assert updated["address"] == source["address"]
    assert updated["revision"] == 2
    # New options change what a fetch returns, so the source is fetched again, at once.
    assert [(str(id), force) for id, force in dispatcher(client).refreshes] == [
        (source["id"], True)
    ]


def test_renaming_a_source_fetches_nothing(client: TestClient, source: dict[str, Any]) -> None:
    response = client.patch(
        f"/api/sources/{source['id']}", json={"expected_revision": 1, "name": "Renamed"}
    )
    assert response.status_code == 200
    assert dispatcher(client).refreshes == []


def test_updating_a_source_from_a_stale_revision_conflicts(
    client: TestClient, source: dict[str, Any]
) -> None:
    client.patch(f"/api/sources/{source['id']}", json={"expected_revision": 1, "name": "A"})
    response = client.patch(
        f"/api/sources/{source['id']}", json={"expected_revision": 1, "name": "B"}
    )
    assert response.status_code == 409
    assert response.json()["revision"] == 2


def test_an_unknown_source_is_not_found(client: TestClient) -> None:
    missing = uuid7()
    assert client.get(f"/api/sources/{missing}").status_code == 404
    patch = client.patch(f"/api/sources/{missing}", json={"expected_revision": 1})
    assert patch.status_code == 404
    assert client.post(f"/api/sources/{missing}/refresh").status_code == 404


def test_registering_a_source_needs_its_fields(client: TestClient, project: dict[str, Any]) -> None:
    response = client.post(f"/api/projects/{project['id']}/sources", json={"name": "x"})
    assert response.status_code == 422
    bad_kind = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"name": "x", "access_kind": "ftp", "address": "a", "format": "csv"},
    )
    assert bad_kind.status_code == 422


def test_refreshing_a_source_queues_a_task_and_answers_202(
    client: TestClient, source: dict[str, Any]
) -> None:
    response = client.post(f"/api/sources/{source['id']}/refresh")
    assert response.status_code == 202
    assert response.json() == {"data_source_id": source["id"], "force": False}

    forced = client.post(f"/api/sources/{source['id']}/refresh", json={"force": True})
    assert forced.status_code == 202
    assert [force for _, force in dispatcher(client).refreshes] == [False, True]
    assert str(dispatcher(client).refreshes[0][0]) == source["id"]


def test_a_refresh_that_cannot_be_queued_answers_503(
    client: TestClient, source: dict[str, Any]
) -> None:
    async def unreachable(data_source_id: UUID, force: bool = False) -> None:
        raise Unavailable("The task queue could not be reached: connection refused")

    dispatcher(client).refresh_source = unreachable  # type: ignore[method-assign]
    response = client.post(f"/api/sources/{source['id']}/refresh")
    assert response.status_code == 503
    assert response.json() == {"detail": "The task queue could not be reached: connection refused"}


# Sessions


def test_sessions_are_created_listed_and_read(
    client: TestClient, project: dict[str, Any], session: dict[str, Any]
) -> None:
    assert session["title"] == "First look"
    assert session["project_id"] == project["id"]
    assert get(client, f"/projects/{project['id']}/sessions") == [session]
    assert get(client, f"/sessions/{session['id']}") == session


def test_a_session_is_renamed_and_its_panel_dashboard_cleared(
    client: TestClient, session: dict[str, Any]
) -> None:
    renamed = client.patch(
        f"/api/sessions/{session['id']}", json={"title": "Deeper", "expected_revision": 1}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Deeper"
    assert renamed.json()["revision"] == 2

    # Null clears the panel, which is a change like any other.
    cleared = client.patch(
        f"/api/sessions/{session['id']}", json={"panel_dashboard_id": None, "expected_revision": 2}
    )
    assert cleared.status_code == 200
    assert cleared.json()["panel_dashboard_id"] is None
    assert cleared.json()["revision"] == 3


def test_a_session_change_must_change_something(
    client: TestClient, session: dict[str, Any]
) -> None:
    response = client.patch(f"/api/sessions/{session['id']}", json={"expected_revision": 1})
    assert response.status_code == 422


def test_showing_an_unknown_dashboard_is_not_found(
    client: TestClient, session: dict[str, Any]
) -> None:
    response = client.patch(
        f"/api/sessions/{session['id']}",
        json={"panel_dashboard_id": str(uuid7()), "expected_revision": 1},
    )
    assert response.status_code == 404


def dashboard(project_id: UUID) -> Dashboard:
    return Dashboard(id=uuid7(), project_id=project_id, name="Overview", created_at=NOW)


def test_a_dashboard_is_shown_in_the_panel_and_must_belong_to_the_project(
    client: TestClient, project: dict[str, Any], session: dict[str, Any]
) -> None:
    # Dashboards have no service in this wave, so the records go into the store directly.
    dashboards = store(client).dashboards
    own = dashboard(UUID(project["id"]))
    foreign = dashboard(uuid7())
    dashboards[own.id] = own
    dashboards[foreign.id] = foreign

    shown = client.patch(
        f"/api/sessions/{session['id']}",
        json={"panel_dashboard_id": str(own.id), "expected_revision": 1},
    )
    assert shown.status_code == 200
    assert shown.json()["panel_dashboard_id"] == str(own.id)

    other = client.patch(
        f"/api/sessions/{session['id']}",
        json={"panel_dashboard_id": str(foreign.id), "expected_revision": 2},
    )
    assert other.status_code == 422
    started_from = client.post(
        f"/api/projects/{project['id']}/sessions",
        json={"title": "From a dashboard", "origin_dashboard_id": str(own.id)},
    )
    assert started_from.status_code == 201
    assert started_from.json()["origin_dashboard_id"] == str(own.id)


def test_session_writes_from_a_stale_revision_conflict(
    client: TestClient, session: dict[str, Any]
) -> None:
    client.patch(f"/api/sessions/{session['id']}", json={"title": "A", "expected_revision": 1})
    response = client.patch(
        f"/api/sessions/{session['id']}", json={"title": "B", "expected_revision": 1}
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": response.json()["detail"],
        "expected_revision": 1,
        "revision": 2,
    }


def test_an_unknown_session_is_not_found(client: TestClient) -> None:
    missing = uuid7()
    assert client.get(f"/api/sessions/{missing}").status_code == 404
    assert client.get(f"/api/sessions/{missing}/entries").status_code == 404
    assert client.get(f"/api/sessions/{missing}/widgets").status_code == 404
    assert client.post(f"/api/sessions/{missing}/messages", json={"text": "hi"}).status_code == 404


def test_a_message_is_recorded_as_the_web_user_and_announced(
    client: TestClient, project: dict[str, Any], session: dict[str, Any]
) -> None:
    entry = post(client, f"/sessions/{session['id']}/messages", {"text": "What changed?"})
    assert entry["kind"] == "message"
    assert entry["text"] == "What changed?"
    assert entry["actor"] == WEB

    assert get(client, f"/sessions/{session['id']}/entries") == [entry]
    created, event = events(client)
    assert created.type == "session.created"
    assert event.type == "session.entry_added"
    assert str(event.project_id) == project["id"]
    assert event.payload == {"session_id": session["id"], "entry_id": entry["id"]}


def test_an_empty_message_is_invalid(client: TestClient, session: dict[str, Any]) -> None:
    response = client.post(f"/api/sessions/{session['id']}/messages", json={"text": " "})
    assert response.status_code == 422


def test_entries_come_oldest_first(client: TestClient, session: dict[str, Any]) -> None:
    for text in ("one", "two", "three"):
        post(client, f"/sessions/{session['id']}/messages", {"text": text})
    texts = [entry["text"] for entry in get(client, f"/sessions/{session['id']}/entries")]
    assert texts == ["one", "two", "three"]


# Operators


def test_a_source_operator_is_added_through_the_pipeline_service(
    client: TestClient, source: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    assert source_operator["kind"] == "source"
    assert source_operator["params"] == {"data_source_id": source["id"]}
    assert source_operator["created_by"] == WEB
    assert get(client, f"/operators/{source_operator['id']}") == source_operator


def test_a_transform_is_added_over_its_inputs(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    transform = post(
        client,
        f"/projects/{project['id']}/operators",
        {
            "kind": "transform",
            "sql": "SELECT region, value FROM input_0",
            "inputs": [source_operator["id"]],
        },
    )
    assert transform["kind"] == "transform"
    assert transform["inputs"] == [source_operator["id"]]
    lineage = get(client, f"/operators/{transform['id']}/lineage")
    assert [operator["id"] for operator in lineage] == [source_operator["id"], transform["id"]]


def test_an_input_operator_is_added(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    operator = post(
        client,
        f"/projects/{project['id']}/operators",
        {
            "kind": "input",
            "name": "rate",
            "output": {"columns": [{"name": "value", "type": "number"}]},
            "default": source_operator["id"],
        },
    )
    assert operator["kind"] == "input"
    assert operator["params"] == {"name": "rate"}


def test_an_operator_added_in_a_session_is_recorded_with_its_note(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source: dict[str, Any],
) -> None:
    operator = post(
        client,
        f"/projects/{project['id']}/operators",
        {
            "kind": "source",
            "data_source_id": source["id"],
            "session_id": session["id"],
            "note": "Need the raw numbers",
        },
    )
    [entry] = get(client, f"/sessions/{session['id']}/entries")
    assert entry["kind"] == "operator"
    assert entry["ref"] == operator["id"]
    assert entry["text"] == "Need the raw numbers"
    assert entry["actor"] == WEB


def test_an_unsupported_operator_kind_is_rejected(
    client: TestClient, project: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/projects/{project['id']}/operators", json={"kind": "agent", "prompt": "x"}
    )
    assert response.status_code == 422


def test_invalid_sql_is_rejected_with_422(client: TestClient, project: dict[str, Any]) -> None:
    response = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "transform", "sql": "DROP TABLE x", "inputs": []},
    )
    assert response.status_code == 422
    assert "Not a query" in response.json()["detail"]


def test_operators_of_an_unknown_source_or_id_are_not_found(
    client: TestClient, project: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "source", "data_source_id": str(uuid7())},
    )
    assert response.status_code == 404
    assert client.get("/api/operators/op_missing").status_code == 404
    assert client.get("/api/operators/op_missing/lineage").status_code == 404


def test_recording_an_operator_in_an_unknown_session_is_not_found(
    client: TestClient, project: dict[str, Any], source: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "source", "data_source_id": source["id"], "session_id": str(uuid7())},
    )
    assert response.status_code == 404


# Runs


def test_a_run_is_started_and_read(client: TestClient, project: dict[str, Any]) -> None:
    run = post(client, f"/projects/{project['id']}/runs")
    assert run["started_by"] == WEB
    assert run["bindings"] == {}
    assert get(client, f"/runs/{run['id']}") == run


def test_a_run_takes_a_time_range_and_bindings(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    run = post(
        client,
        f"/projects/{project['id']}/runs",
        {"time_range": {"start": "2020-01-01", "end": "2024-12-31"}, "bindings": {"rate": "op_x"}},
    )
    assert run["time_range"] == {"start": "2020-01-01", "end": "2024-12-31"}
    assert run["bindings"] == {"rate": "op_x"}


def test_runs_of_unknown_projects_and_ids_are_not_found(client: TestClient) -> None:
    assert client.post(f"/api/projects/{uuid7()}/runs").status_code == 404
    assert client.get(f"/api/runs/{uuid7()}").status_code == 404


def test_rows_of_an_operator_are_read_with_a_limit(
    client: TestClient,
    project: dict[str, Any],
    source_operator: dict[str, Any],
    overrides: Overrides,
) -> None:
    run = post(client, f"/projects/{project['id']}/runs")
    path = f"/runs/{run['id']}/operators/{source_operator['id']}/rows"
    rows = get(client, path)
    assert [column["name"] for column in rows["columns"]] == ["region", "value"]
    assert rows["rows"] == [["north", 1.5], ["south", 2.5]]
    assert rows["truncated"] is False

    limited = get(client, f"{path}?limit=1")
    assert limited["rows"] == [["north", 1.5]]
    assert limited["truncated"] is True
    assert overrides.results.reads[-1][2] == 1


@pytest.mark.parametrize("limit", ["0", "-1", "many", "1000000"])
def test_row_limits_out_of_range_are_rejected(
    client: TestClient, project: dict[str, Any], limit: str
) -> None:
    run = post(client, f"/projects/{project['id']}/runs")
    response = client.get(f"/api/runs/{run['id']}/operators/op_x/rows?limit={limit}")
    assert response.status_code == 422


# Widgets


def create_widget(
    client: TestClient, project: dict[str, Any], operator: dict[str, Any], **body: Any
) -> dict[str, Any]:
    return post(
        client,
        f"/projects/{project['id']}/widgets",
        {"operator_id": operator["id"], "type": "table", "title": "Regions", **body},
    )


def test_a_widget_is_created_from_an_operator_id_and_read(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    widget = create_widget(client, project, source_operator, spec={"x": "region"})
    assert widget["operator_id"] == source_operator["id"]
    assert widget["session_id"] is None
    assert widget["spec"] == {"x": "region"}
    assert widget["created_by"] == WEB
    assert get(client, f"/widgets/{widget['id']}") == widget
    [event] = events(client)
    assert event.type == "widget.created"
    assert event.payload == {"widget_id": widget["id"]}


def test_a_widget_has_no_way_to_carry_data(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    path = f"/api/projects/{project['id']}/widgets"
    body = {"operator_id": source_operator["id"], "type": "table", "title": "t"}
    assert client.post(path, json={**body, "rows": [["a", 1]]}).status_code == 422
    assert client.post(path, json={**body, "data": {"rows": []}}).status_code == 422

    widget = create_widget(client, project, source_operator)
    assert get(client, f"/widgets/{widget['id']}/data")["rows"] == [["north", 1.5], ["south", 2.5]]


def test_a_project_lists_all_its_widgets(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    in_session = create_widget(client, project, source_operator, session_id=session["id"])
    loose = create_widget(client, project, source_operator)
    assert get(client, f"/projects/{project['id']}/widgets") == [in_session, loose]
    assert client.get(f"/api/projects/{uuid7()}/widgets").status_code == 404


def test_a_widget_in_a_session_is_recorded_and_listed(
    client: TestClient,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    widget = create_widget(
        client, project, source_operator, session_id=session["id"], note="Shows the regions"
    )
    assert widget["session_id"] == session["id"]
    assert widget["note"] == "Shows the regions"
    assert get(client, f"/sessions/{session['id']}/widgets") == [widget]

    [entry] = get(client, f"/sessions/{session['id']}/entries")
    assert entry["kind"] == "widget"
    assert entry["ref"] == widget["id"]
    assert entry["text"] == "Shows the regions"
    assert entry["actor"] == WEB
    assert [event.type for event in events(client)] == [
        "session.created",
        "widget.created",
        "session.entry_added",
    ]
    assert events(client)[1].payload == {"widget_id": widget["id"], "session_id": session["id"]}


def test_widgets_of_unknown_things_are_not_found(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    assert client.get(f"/api/widgets/{uuid7()}").status_code == 404
    assert client.get(f"/api/widgets/{uuid7()}/data").status_code == 404
    path = f"/api/projects/{project['id']}/widgets"
    body = {"type": "table", "title": "t"}
    assert client.post(path, json={**body, "operator_id": "op_missing"}).status_code == 404
    unknown_session = {**body, "operator_id": source_operator["id"], "session_id": str(uuid7())}
    assert client.post(path, json=unknown_session).status_code == 404
    assert client.post(f"/api/projects/{uuid7()}/widgets", json=unknown_session).status_code == 404


def test_a_widget_needs_a_type_and_an_operator(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    path = f"/api/projects/{project['id']}/widgets"
    assert client.post(path, json={"type": "table", "title": "t"}).status_code == 422
    blank = {"operator_id": source_operator["id"], "type": " ", "title": "t"}
    assert client.post(path, json=blank).status_code == 422


def test_a_widget_cannot_use_an_operator_of_another_project(
    client: TestClient, source_operator: dict[str, Any]
) -> None:
    other = post(client, "/projects", {"name": "Other"})
    response = client.post(
        f"/api/projects/{other['id']}/widgets",
        json={"operator_id": source_operator["id"], "type": "table", "title": "t"},
    )
    assert response.status_code == 422


def test_widget_data_starts_a_run_without_a_run_id(
    client: TestClient,
    project: dict[str, Any],
    source_operator: dict[str, Any],
    overrides: Overrides,
) -> None:
    widget = create_widget(client, project, source_operator)
    data = get(client, f"/widgets/{widget['id']}/data")
    assert data["widget_id"] == widget["id"]
    assert [column["name"] for column in data["columns"]] == ["region", "value"]
    assert data["is_scenario"] is False
    assert data["is_stale"] is False
    # What the columns mean comes along, so the widget needs no request for its operator.
    assert data["output"] == source_operator["output"]
    run = get(client, f"/runs/{data['run_id']}")
    assert run["bindings"] == {}
    assert run["time_range"] == {"start": None, "end": None}
    assert run["started_by"]["kind"] == "system"


def test_widget_data_in_a_given_run_marks_scenarios(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    widget = create_widget(client, project, source_operator)
    run = post(client, f"/projects/{project['id']}/runs", {"bindings": {"rate": "op_x"}})
    data = get(client, f"/widgets/{widget['id']}/data?run_id={run['id']}&limit=1")
    assert data["run_id"] == run["id"]
    assert data["is_scenario"] is True
    assert data["rows"] == [["north", 1.5]]
    assert data["truncated"] is True


def test_widget_data_is_stale_while_a_source_upstream_failed_its_refresh(
    client: TestClient,
    project: dict[str, Any],
    source: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    transform = post(
        client,
        f"/projects/{project['id']}/operators",
        {"kind": "transform", "sql": "SELECT * FROM input_0", "inputs": [source_operator["id"]]},
    )
    widget = create_widget(client, project, transform)
    assert get(client, f"/widgets/{widget['id']}/data")["is_stale"] is False

    # What the worker's failed refresh leaves on the source.
    memory = store(client)
    failed = memory.data_sources[UUID(source["id"])]
    memory.data_sources[failed.id] = failed.model_copy(update={"last_error": "HTTP 503"})

    assert get(client, f"/widgets/{widget['id']}/data")["is_stale"] is True


def test_widget_data_in_a_run_of_another_project_is_invalid(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    widget = create_widget(client, project, source_operator)
    other = post(client, "/projects", {"name": "Other"})
    run = post(client, f"/projects/{other['id']}/runs")
    response = client.get(f"/api/widgets/{widget['id']}/data?run_id={run['id']}")
    assert response.status_code == 422


def test_widget_data_in_an_unknown_run_is_not_found(
    client: TestClient, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    widget = create_widget(client, project, source_operator)
    assert client.get(f"/api/widgets/{widget['id']}/data?run_id={uuid7()}").status_code == 404


def test_the_openapi_schema_lists_every_route_of_the_contract(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    expected = {
        ("get", "/api/projects"),
        ("post", "/api/projects"),
        ("get", "/api/projects/{project_id}"),
        ("patch", "/api/projects/{project_id}"),
        ("get", "/api/projects/{project_id}/sources"),
        ("post", "/api/projects/{project_id}/sources"),
        ("get", "/api/sources/{source_id}"),
        ("patch", "/api/sources/{source_id}"),
        ("post", "/api/sources/{source_id}/refresh"),
        ("get", "/api/projects/{project_id}/sessions"),
        ("post", "/api/projects/{project_id}/sessions"),
        ("get", "/api/sessions/{session_id}"),
        ("patch", "/api/sessions/{session_id}"),
        ("get", "/api/sessions/{session_id}/entries"),
        ("post", "/api/sessions/{session_id}/messages"),
        ("get", "/api/sessions/{session_id}/widgets"),
        ("post", "/api/projects/{project_id}/operators"),
        ("get", "/api/operators/{operator_id}"),
        ("get", "/api/operators/{operator_id}/lineage"),
        ("post", "/api/projects/{project_id}/runs"),
        ("get", "/api/runs/{run_id}"),
        ("get", "/api/runs/{run_id}/operators/{operator_id}/rows"),
        ("post", "/api/projects/{project_id}/widgets"),
        ("get", "/api/widgets/{widget_id}"),
        ("get", "/api/widgets/{widget_id}/data"),
    }
    served = {(method, path) for path, methods in paths.items() for method in methods}
    assert expected <= served
