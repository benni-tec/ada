"""The alert routes and MCP tools, over the real services, DuckDB in tmp_path and the memory
repositories (alerts_support.py)."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.events import EventType
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from alerts_support import AlertOverrides, Setup, World, below, csv
from memory import memory_adapters

DATA = csv(("north", 2023, 85), ("north", 2024, 70), ("south", 2023, 90), ("south", 2024, 92))
BAD_FORMULA = {
    "id": "low",
    "kind": "compare",
    "op": "<",
    "args": [
        {"id": "where", "kind": "column", "column": "nowhere"},
        {"id": "limit", "kind": "constant", "value": 80},
    ],
}


def rule_body(setup: Setup, **changes: Any) -> dict[str, Any]:
    return {
        "name": "Coverage below target",
        "operator_id": setup.measure.id,
        "formula": below(80),
        "key_columns": ["region"],
    } | changes


# REST


@pytest.fixture
def rest(unreachable_settings: Settings) -> Iterator[tuple[TestClient, World]]:
    overrides = AlertOverrides()
    app = create_app(unreachable_settings, *memory_adapters(), overrides)
    with TestClient(app) as client:
        container: AsyncContainer = client.app.state.dishka_container  # type: ignore[attr-defined]
        yield client, World(container, overrides)


@pytest.fixture
def client(rest: tuple[TestClient, World]) -> TestClient:
    return rest[0]


@pytest.fixture
def world(rest: tuple[TestClient, World]) -> World:
    return rest[1]


@pytest.fixture
def setup(client: TestClient, world: World) -> Setup:
    assert client.portal is not None
    return client.portal.call(world.setup, DATA)


def created_rule(client: TestClient, setup: Setup, **changes: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/dashboards/{setup.dashboard.id}/alert-rules", json=rule_body(setup, **changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rules_are_created_listed_read_and_updated(client: TestClient, setup: Setup) -> None:
    rule = created_rule(client, setup, severity="critical", check_interval_seconds=3600)
    assert rule["dashboard_id"] == str(setup.dashboard.id)
    assert rule["severity"] == "critical"
    assert rule["key_columns"] == ["region"]
    dashboard = setup.dashboard.id
    assert client.get(f"/api/dashboards/{dashboard}/alert-rules").json() == [rule]
    assert client.get(f"/api/alert-rules/{rule['id']}").json() == rule

    response = client.patch(
        f"/api/alert-rules/{rule['id']}",
        json={"expected_revision": 1, "name": "Too low", "enabled": False},
    )
    assert response.status_code == 200, response.text
    assert (response.json()["name"], response.json()["enabled"]) == ("Too low", False)
    assert response.json()["revision"] == 2

    stale = client.patch(f"/api/alert-rules/{rule['id']}", json={"expected_revision": 1})
    assert stale.status_code == 409
    assert (stale.json()["expected_revision"], stale.json()["revision"]) == (1, 2)

    grouped = client.get(f"/api/projects/{setup.project_id}/alert-rules").json()
    assert [(g["dashboard"]["id"], [r["name"] for r in g["rules"]]) for g in grouped] == [
        (str(dashboard), ["Too low"])
    ]


def test_invalid_rules_answer_with_the_node_at_fault(client: TestClient, setup: Setup) -> None:
    url = f"/api/dashboards/{setup.dashboard.id}/alert-rules"
    response = client.post(url, json=rule_body(setup, formula=BAD_FORMULA))
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Formula node 'where': 'nowhere' is not a column")
    assert client.post(url, json=rule_body(setup, colour="red")).status_code == 422
    unknown = client.post(
        "/api/dashboards/01900000-0000-7000-8000-000000000000/alert-rules", json=rule_body(setup)
    )
    assert unknown.status_code == 404
    rule = created_rule(client, setup)
    patched = client.patch(
        f"/api/alert-rules/{rule['id']}", json={"expected_revision": 1, "formula": BAD_FORMULA}
    )
    assert patched.status_code == 422
    assert "Formula node 'where'" in patched.json()["detail"]


def test_a_check_answers_with_the_changes_and_the_feed_shows_them(
    client: TestClient, world: World, setup: Setup
) -> None:
    rule = created_rule(client, setup)
    response = client.post(f"/api/alert-rules/{rule['id']}/check")
    assert response.status_code == 200, response.text
    result = response.json()
    (alert,) = result["changed"]
    assert alert["key"] == {"region": "north"}
    assert alert["state"] == "firing"
    assert result["firing"] == [alert]
    assert result["rule"]["last_checked_at"] is not None

    # The run's rows of the alerting operator are what the alert links to.
    lineage = client.get(f"/api/operators/{setup.measure.id}/lineage")
    assert lineage.status_code == 200

    feed = client.get(f"/api/projects/{setup.project_id}/alerts").json()
    assert [(view["alert"]["id"], view["rule"]["name"]) for view in feed] == [
        (alert["id"], "Coverage below target")
    ]
    assert client.get(f"/api/projects/{setup.project_id}/alerts?state=resolved").json() == []
    assert client.get(f"/api/dashboards/{setup.dashboard.id}/alerts?state=firing").json() == feed
    assert client.get(f"/api/projects/{setup.project_id}/alerts?state=burning").status_code == 422

    assert client.portal is not None
    types = [event.type for event in client.portal.call(world.events)]
    assert EventType.ALERT_FIRING in types


def test_the_feed_lists_firing_alerts_first(client: TestClient, world: World, setup: Setup) -> None:
    rule = created_rule(client, setup)
    client.post(f"/api/alert-rules/{rule['id']}/check")
    assert client.portal is not None
    world.clock.advance(days=1)
    client.portal.call(world.refetch, setup.source, csv(("north", 2025, 90), ("south", 2025, 60)))
    client.post(f"/api/alert-rules/{rule['id']}/check")
    feed = client.get(f"/api/projects/{setup.project_id}/alerts").json()
    assert [(v["alert"]["key"]["region"], v["alert"]["state"]) for v in feed] == [
        ("south", "firing"),
        ("north", "resolved"),
    ]


def test_a_dashboard_without_rules_has_no_alerts(client: TestClient, setup: Setup) -> None:
    assert client.get(f"/api/dashboards/{setup.dashboard.id}/alerts").json() == []
    unknown = client.get("/api/projects/01900000-0000-7000-8000-000000000000/alerts")
    assert unknown.status_code == 404


# MCP


@pytest.fixture
async def mcp_world(unreachable_settings: Settings) -> AsyncIterator[World]:
    overrides = AlertOverrides()
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), overrides
    )
    try:
        yield World(container, overrides)
    finally:
        await container.close()


@pytest.fixture
async def mcp(mcp_world: World) -> AsyncIterator[Client]:
    info = Implementation(name="claude-code", version="2.0")
    async with Client(create_mcp(mcp_world.container), client_info=info) as client:
        yield client


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


@pytest.mark.anyio
async def test_the_alert_tools_are_served_and_documented(mcp: Client) -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    names = {
        "create_alert_rule",
        "list_alert_rules",
        "get_alert_rule",
        "update_alert_rule",
        "check_alert_rule",
        "list_alerts",
    }
    assert names <= set(tools)
    create = tools["create_alert_rule"]
    assert create.description is not None
    # The formula format is in the tool's own description, with an example.
    for word in ("rolling_mean", "previous", "suppressed", '"kind": "compare"', "key_columns"):
        assert word in create.description
    assert set(create.input_schema["properties"]) == {
        "dashboard_id",
        "name",
        "operator_id",
        "formula",
        "key_columns",
        "severity",
        "check_interval_seconds",
        "max_data_age_seconds",
        "alert_pipeline_id",
    }


@pytest.mark.anyio
async def test_an_agent_creates_checks_and_reads_alerts(mcp: Client, mcp_world: World) -> None:
    setup = await mcp_world.setup(DATA)
    rule = await call(
        mcp,
        "create_alert_rule",
        dashboard_id=str(setup.dashboard.id),
        name="Coverage below target",
        operator_id=setup.measure.id,
        formula=below(80),
        key_columns=["region"],
        severity="critical",
    )
    assert rule["severity"] == "critical"
    assert await call(mcp, "list_alert_rules", dashboard_id=str(setup.dashboard.id)) == [rule]
    assert await call(mcp, "get_alert_rule", rule_id=rule["id"]) == rule

    checked = await call(mcp, "check_alert_rule", rule_id=rule["id"])
    (alert,) = checked["changed"]
    assert alert["key"] == {"region": "north"}
    assert checked["firing"] == [alert]

    feed = await call(mcp, "list_alerts", project_id=str(setup.project_id), state="firing")
    assert [(e["alert"]["id"], e["rule_name"], e["severity"]) for e in feed] == [
        (alert["id"], "Coverage below target", "critical")
    ]
    assert feed[0]["url"] == f"/projects/{setup.project_id}/alerts"

    updated = await call(
        mcp, "update_alert_rule", rule_id=rule["id"], expected_revision=1, formula=below(50)
    )
    assert updated["revision"] == 2
    checked = await call(mcp, "check_alert_rule", rule_id=rule["id"])
    assert [(a["key"], a["state"]) for a in checked["changed"]] == [
        ({"region": "north"}, "resolved")
    ]


@pytest.mark.anyio
async def test_tool_errors_name_the_formula_node(mcp: Client, mcp_world: World) -> None:
    setup = await mcp_world.setup(DATA)
    with pytest.raises(ToolError, match="Formula node 'where'"):
        await mcp.call_tool(
            "create_alert_rule",
            {
                "dashboard_id": str(setup.dashboard.id),
                "name": "Broken",
                "operator_id": setup.measure.id,
                "formula": BAD_FORMULA,
                "key_columns": ["region"],
            },
        )
