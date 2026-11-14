"""The REST routes of reports, report versions and templates."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid7

import pytest
from fastapi.testclient import TestClient

from ada.adapters.memory.events import MemoryEventBus
from ada.config import Settings
from ada.entrypoints.http.app import create_app
from memory import memory_adapters
from test_api_support import Overrides
from test_reports_support import ReportFakes, Scene, blocks, heading, seed, shows, text

WEB = {"kind": "user", "name": "web"}


@pytest.fixture
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    app = create_app(unreachable_settings, *memory_adapters(), Overrides(), ReportFakes())
    with TestClient(app) as client:
        yield client


@pytest.fixture
def scene(client: TestClient) -> Scene:
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    return client.portal.call(seed, container)


def post(client: TestClient, path: str, body: dict[str, Any], status: int = 201) -> Any:
    response = client.post(f"/api{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


def get(client: TestClient, path: str) -> Any:
    response = client.get(f"/api{path}")
    assert response.status_code == 200, response.text
    return response.json()


def create(client: TestClient, scene: Scene, **body: Any) -> dict[str, Any]:
    return post(
        client,
        f"/projects/{scene.project.id}/reports",
        {
            "name": "Findings",
            "content": blocks(heading("Gap"), shows(scene.value)),
            "session_id": str(scene.session.id),
        }
        | body,
    )


def test_a_report_is_created_listed_and_read(client: TestClient, scene: Scene) -> None:
    version = create(client, scene)
    assert version["version"] == "1.0.0"
    assert version["created_by"] == WEB
    # No run named: one was started, with an open range.
    run = get(client, f"/runs/{version['run_id']}")
    assert version["time_range"] == run["time_range"] == {"start": None, "end": None}

    report = get(client, f"/reports/{version['report_id']}")
    assert report["latest_version_id"] == version["id"]
    assert get(client, f"/projects/{scene.project.id}/reports") == [report]
    assert get(client, f"/reports/{report['id']}/versions") == [version]
    assert get(client, f"/report-versions/{version['id']}") == version


def test_a_report_pins_the_run_it_is_given(client: TestClient, scene: Scene) -> None:
    run = post(
        client,
        f"/projects/{scene.project.id}/runs",
        {"time_range": {"start": "2024-01-01", "end": "2024-12-31"}},
    )
    version = create(client, scene, run_id=run["id"])
    assert version["run_id"] == run["id"]
    assert version["time_range"] == {"start": "2024-01-01", "end": "2024-12-31"}

    response = client.post(
        f"/api/projects/{scene.project.id}/reports",
        json={
            "name": "Other",
            "content": blocks(shows(scene.value)),
            "session_id": str(scene.session.id),
            "run_id": run["id"],
            "time_range": {"start": "2020-01-01"},
        },
    )
    assert response.status_code == 422
    assert "was started for" in response.json()["detail"]


def test_an_invalid_tree_is_a_422_and_stores_nothing(client: TestClient, scene: Scene) -> None:
    response = client.post(
        f"/api/projects/{scene.project.id}/reports",
        json={
            "name": "Findings",
            "content": blocks({"type": "text", "text": "x", "rows": [[1, 2]]}),
            "session_id": str(scene.session.id),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("blocks[0].rows: not a field")
    assert get(client, f"/projects/{scene.project.id}/reports") == []


def test_unknown_records_are_not_found(client: TestClient) -> None:
    assert client.get(f"/api/reports/{uuid7()}").status_code == 404
    assert client.get(f"/api/reports/{uuid7()}/versions").status_code == 404
    assert client.get(f"/api/report-versions/{uuid7()}").status_code == 404
    assert client.get(f"/api/report-versions/{uuid7()}/sources").status_code == 404
    assert client.get(f"/api/projects/{uuid7()}/reports").status_code == 404
    assert client.get(f"/api/templates/{uuid7()}").status_code == 404


def test_a_version_is_added_with_its_level_inferred(client: TestClient, scene: Scene) -> None:
    first = create(client, scene)
    report_id = first["report_id"]
    patch = post(
        client,
        f"/reports/{report_id}/versions",
        {
            "content": blocks(heading("The gap"), shows(scene.value)),
            "run_id": first["run_id"],
            "expected_revision": 1,
        },
    )
    assert patch["version"] == "1.0.1"
    # Without a run, a new one is started: the same report on new data.
    minor = post(
        client,
        f"/reports/{report_id}/versions",
        {"content": blocks(heading("The gap"), shows(scene.value))},
    )
    assert minor["version"] == "1.1.0"
    major = post(
        client,
        f"/reports/{report_id}/versions",
        {"content": blocks(shows(scene.chart)), "run_id": minor["run_id"], "bump": "major"},
    )
    assert major["version"] == "2.0.0"
    numbers = [v["version"] for v in get(client, f"/reports/{report_id}/versions")]
    assert numbers == ["1.0.0", "1.0.1", "1.1.0", "2.0.0"]


def test_a_version_from_a_stale_revision_conflicts(client: TestClient, scene: Scene) -> None:
    first = create(client, scene)
    body = {"content": blocks(text("Mine"), shows(scene.value)), "run_id": first["run_id"]}
    post(client, f"/reports/{first['report_id']}/versions", body | {"expected_revision": 1})
    response = client.post(
        f"/api/reports/{first['report_id']}/versions",
        json=body | {"content": blocks(text("Theirs"), shows(scene.value)), "expected_revision": 1},
    )
    assert response.status_code == 409
    assert response.json()["expected_revision"] == 1
    assert response.json()["revision"] == 2


def test_a_too_small_level_is_a_422(client: TestClient, scene: Scene) -> None:
    first = create(client, scene)
    response = client.post(
        f"/api/reports/{first['report_id']}/versions",
        json={"content": blocks(shows(scene.chart)), "bump": "patch"},
    )
    assert response.status_code == 422
    assert "too small" in response.json()["detail"]


def test_the_sources_list_is_served(client: TestClient, scene: Scene) -> None:
    version = create(client, scene, content=blocks(shows(scene.chart)))
    sources = get(client, f"/report-versions/{version['id']}/sources")
    assert sources == version["content"]["sources"]
    assert [source["name"] for source in sources] == ["Sotkanet", "Statistics Finland"]
    assert sources[0]["fetched_at"] == "2025-12-01T08:00:00Z"


def test_a_dashboard_is_generated_into_a_report(client: TestClient, scene: Scene) -> None:
    first = post(client, f"/dashboards/{scene.dashboard.id}/reports", {"name": "Monthly"})
    assert first["version"] == "1.0.0"
    assert first["dashboard_version_id"] == str(scene.dashboard_version.id)
    assert first["time_range"] == {"start": "2024-01-01", "end": "2024-12-31"}
    again = post(client, f"/dashboards/{scene.dashboard.id}/reports", {"name": "Monthly"})
    assert again["report_id"] == first["report_id"]
    assert again["version"] == "1.1.0"

    create(client, scene)
    by_dashboard = get(
        client, f"/projects/{scene.project.id}/reports?dashboard_id={scene.dashboard.id}"
    )
    assert [report["id"] for report in by_dashboard] == [first["report_id"]]
    by_session = get(client, f"/projects/{scene.project.id}/reports?session_id={scene.session.id}")
    assert [report["name"] for report in by_session] == ["Findings"]


def test_a_new_version_is_announced(client: TestClient, scene: Scene) -> None:
    version = create(client, scene)
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    bus = client.portal.call(container.get, MemoryEventBus)
    [event] = [e for e in bus.published if e.type == "report.version_created"]
    assert event.payload == {
        "report_id": version["report_id"],
        "version_id": version["id"],
        "version": "1.0.0",
    }


def test_templates_are_created_listed_and_filled(client: TestClient, scene: Scene) -> None:
    template = post(
        client,
        f"/projects/{scene.project.id}/templates",
        {
            "name": "Brief",
            "kind": "report",
            "slots": [{"name": "gap", "description": "The headline gap"}],
            "content": blocks(heading("Gap"), {"type": "widget", "slot": "gap"}),
        },
    )
    assert template["revision"] == 1
    assert get(client, f"/templates/{template['id']}") == template
    assert get(client, f"/projects/{scene.project.id}/templates") == [template]

    version = create(
        client,
        scene,
        content={"slots": {"gap": str(scene.value.id)}},
        template_id=template["id"],
    )
    assert version["template_id"] == template["id"]
    assert version["content"]["blocks"][1]["widget_id"] == str(scene.value.id)


def test_a_wrong_template_is_a_422(client: TestClient, scene: Scene) -> None:
    response = client.post(
        f"/api/projects/{scene.project.id}/templates",
        json={"name": "Brief", "kind": "report", "slots": [{"name": "a"}, {"name": "a"}]},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/projects/{scene.project.id}/templates",
        json={"name": "Brief", "kind": "poster", "slots": [{"name": "a"}]},
    )
    assert response.status_code == 422
