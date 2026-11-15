from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ada.entrypoints.http.app import create_app
from api_support import new_project, send
from conftest import settings_in

VISITOR = {"X-Ada-Visitor": "1"}
type Demo = tuple[TestClient, dict[str, Any], dict[str, Any]]


@pytest.fixture
def demo(migrated_database_url: str, tmp_path: Path) -> Iterator[Demo]:
    """A demo project with a session, protected, and a visitor's own project."""
    settings = settings_in(tmp_path, migrated_database_url)
    with TestClient(create_app(settings)) as team:
        project = new_project(team, "Demo")
        session = send(team, "POST", f"/projects/{project['id']}/sessions", {"title": "Ask"}, 201)
        own = new_project(team, "Mine")
    guarded = settings.model_copy(update={"demo_protected_projects": {UUID(project["id"])}})
    with TestClient(create_app(guarded), raise_server_exceptions=False) as client:
        yield client, session, own


def test_a_visitor_cannot_change_a_demo_project_but_their_own(demo: Demo) -> None:
    client, session, own = demo
    rename = {"title": "Mine now", "expected_revision": session["revision"]}

    refused = client.patch(f"/api/sessions/{session['id']}", json=rename, headers=VISITOR)
    renamed = {"name": "Renamed", "expected_revision": own["revision"]}
    elsewhere = client.patch(f"/api/projects/{own['id']}", json=renamed, headers=VISITOR)
    team = client.patch(f"/api/sessions/{session['id']}", json=rename)

    assert refused.status_code == 403
    assert refused.json()["detail"].startswith("This is a team demo project.")
    assert elsewhere.status_code == 200, elsewhere.text
    assert team.status_code == 200, team.text


def test_a_visitor_may_still_chat_in_a_demo_project(demo: Demo) -> None:
    client, session, _ = demo
    path = f"/api/sessions/{session['id']}/messages"

    response = client.post(path, json={"text": "What changed?"}, headers=VISITOR)

    assert response.status_code != 403
