"""Deleting a session: its messages, attachments, agent turns and the reports it owns go,
other sessions stop showing it, and its widgets and research sessions stay in the project.
Refused while its agent is working."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient

from ada.config import Settings
from ada.core.models.agents import AgentTurn, TurnStatus
from ada.core.models.events import EventType
from ada.core.models.reports import Report
from ada.core.models.sessions import Session
from api_support import Overrides, new_project, resolve, send, serve, store
from memory import MemoryEventBus


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


def test_deleting_a_session_keeps_its_widgets_and_research_sessions(client: TestClient) -> None:
    project = new_project(client)
    doomed = send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "Doomed"}, 201)
    other = send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "Other"}, 201)
    send(client, "POST", f"/sessions/{doomed['id']}/messages", {"text": "Hello"}, 201)
    send(
        client,
        "POST",
        f"/sessions/{other['id']}/attachments",
        {"kind": "session", "ref": doomed["id"]},
        201,
    )
    operator = send(
        client,
        "POST",
        f"/projects/{project['id']}/operators",
        {"kind": "transform", "sql": "SELECT 1 AS one", "inputs": []},
        201,
    )
    widget = send(
        client,
        "POST",
        f"/projects/{project['id']}/widgets",
        {
            "operator_id": operator["id"],
            "type": "table",
            "title": "Made here",
            "session_id": doomed["id"],
        },
        201,
    )
    memory = store(client)
    doomed_id = UUID(doomed["id"])
    report = Report(
        id=uuid7(),
        project_id=UUID(project["id"]),
        name="Owned by it",
        session_id=doomed_id,
        created_at=datetime.now(UTC),
    )
    memory.reports[report.id] = report
    child = Session(
        id=uuid7(),
        project_id=UUID(project["id"]),
        title="Research",
        parent_session_id=doomed_id,
        created_at=datetime.now(UTC),
    )
    memory.sessions[child.id] = child

    response = client.delete(f"/api/sessions/{doomed['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/sessions/{doomed['id']}").status_code == 404
    titles = [s["title"] for s in send(client, "GET", f"/projects/{project['id']}/sessions")]
    assert "Doomed" not in titles and "Other" in titles
    # Its widgets and research sessions stay, unlinked; the reports it owned go with it.
    assert send(client, "GET", f"/widgets/{widget['id']}")["session_id"] is None
    assert memory.sessions[child.id].parent_session_id is None
    assert report.id not in memory.reports
    # Its messages are gone, and the other session no longer shows it.
    assert not [e for e in memory.session_entries if e.session_id == doomed_id]
    assert send(client, "GET", f"/sessions/{other['id']}/attachments") == []
    published = resolve(client, MemoryEventBus).published
    assert any(
        e.type is EventType.SESSION_DELETED and e.payload["session_id"] == doomed["id"]
        for e in published
    )
    assert client.delete(f"/api/sessions/{doomed['id']}").status_code == 404


def test_a_session_whose_agent_is_working_is_not_deleted(client: TestClient) -> None:
    project = new_project(client)
    busy = send(client, "POST", f"/projects/{project['id']}/sessions", {"title": "Busy"}, 201)
    entry = send(client, "POST", f"/sessions/{busy['id']}/messages", {"text": "Go"}, 201)
    turn = AgentTurn(
        id=uuid7(),
        session_id=UUID(busy["id"]),
        prompt_entry_id=UUID(entry["entry"]["id"]),
        model="test/model",
        status=TurnStatus.RUNNING,
        created_at=datetime.now(UTC),
    )
    store(client).agent_turns[turn.id] = turn
    response = client.delete(f"/api/sessions/{busy['id']}")
    assert response.status_code == 422
    assert "still working" in response.json()["detail"]
    store(client).agent_turns[turn.id] = turn.model_copy(update={"status": TurnStatus.DONE})
    assert client.delete(f"/api/sessions/{busy['id']}").status_code == 204
