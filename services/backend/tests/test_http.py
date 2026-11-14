from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ada.config import Settings
from ada.entrypoints.http.app import create_app
from conftest import UNREACHABLE_HEALTH


@pytest.fixture
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(unreachable_settings)) as client:
        yield client


def test_health_reports_unreachable_dependencies(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == UNREACHABLE_HEALTH


def test_liveness_ignores_dependencies(client: TestClient) -> None:
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_is_served_under_api(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_endpoint_answers_initialize(client: TestClient, path: str) -> None:
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
