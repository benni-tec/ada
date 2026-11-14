"""The MCP tools of reports and templates."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.events import EventType
from ada.entrypoints.mcp.server import create_mcp
from memory import memory_adapters
from test_api_support import Overrides
from test_reports_support import ReportFakes, Scene, blocks, heading, published, seed, shows

pytestmark = pytest.mark.anyio

AGENT = {"kind": "external_agent", "name": "claude-code"}

TOOLS = {
    "create_report",
    "add_report_version",
    "generate_report_from_dashboard",
    "list_reports",
    "get_report",
    "create_template",
    "list_templates",
}


@pytest.fixture
async def container(unreachable_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), Overrides(), ReportFakes()
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def client(container: AsyncContainer) -> AsyncIterator[Client]:
    info = Implementation(name="claude-code", version="2.0")
    async with Client(create_mcp(container), client_info=info) as client:
        yield client


@pytest.fixture
async def scene(container: AsyncContainer) -> Scene:
    return await seed(container)


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


async def test_the_report_tools_are_served_and_documented(client: Client) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}
    assert TOOLS <= set(tools)
    injected = {"reports", "runs", "templates"}
    for name in TOOLS:
        assert not set(tools[name].input_schema.get("properties", {})) & injected, name
    # An agent learns the tree from the tools that take one.
    for name in ("create_report", "add_report_version"):
        description = tools[name].description or ""
        assert '"type": "widget", "widget_id"' in description, name
        assert "Leave out `sources`" in description, name


async def test_a_report_is_written_read_and_versioned(client: Client, scene: Scene) -> None:
    created = await call(
        client,
        "create_report",
        project_id=str(scene.project.id),
        name="Findings",
        content=blocks(heading("Gap"), shows(scene.value)),
        session_id=str(scene.session.id),
    )
    report, version = created["report"], created["version"]
    assert version["version"] == "1.0.0"
    assert version["created_by"] == AGENT
    assert created["versions"] == ["1.0.0"]
    assert created["url"] == f"/projects/{scene.project.id}/reports/{report['id']}?version=1.0.0"
    assert [s["name"] for s in version["content"]["sources"]] == ["Sotkanet"]

    added = await call(
        client,
        "add_report_version",
        report_id=report["id"],
        content=blocks(heading("Gap"), shows(scene.value), shows(scene.chart)),
        run_id=version["run_id"],
        expected_revision=1,
    )
    assert added["version"]["version"] == "2.0.0"
    assert added["versions"] == ["1.0.0", "2.0.0"]

    latest = await call(client, "get_report", report_id=report["id"])
    assert latest["version"]["id"] == added["version"]["id"]
    first = await call(client, "get_report", report_id=report["id"], version="1.0.0")
    assert first["version"]["id"] == version["id"]
    assert first["url"].endswith("?version=1.0.0")

    listed = await call(client, "list_reports", project_id=str(scene.project.id))
    assert [item["report"]["name"] for item in listed] == ["Findings"]
    assert listed[0]["url"] == f"/projects/{scene.project.id}/reports/{report['id']}"


async def test_errors_come_back_as_tool_errors(client: Client, scene: Scene) -> None:
    with pytest.raises(ToolError, match="unknown component 'chart'"):
        await client.call_tool(
            "create_report",
            {
                "project_id": str(scene.project.id),
                "name": "Findings",
                "content": blocks({"type": "chart"}),
                "session_id": str(scene.session.id),
            },
        )
    created = await call(
        client,
        "create_report",
        project_id=str(scene.project.id),
        name="Findings",
        content=blocks(shows(scene.value)),
        session_id=str(scene.session.id),
    )
    with pytest.raises(ToolError, match="revision 1, but the write expected revision 3"):
        await client.call_tool(
            "add_report_version",
            {
                "report_id": created["report"]["id"],
                "content": blocks(shows(scene.table)),
                "expected_revision": 3,
            },
        )
    with pytest.raises(ToolError, match="report version 9.9.9"):
        await client.call_tool(
            "get_report", {"report_id": created["report"]["id"], "version": "9.9.9"}
        )


async def test_a_dashboard_is_generated_into_a_report(
    client: Client, scene: Scene, container: AsyncContainer
) -> None:
    generated = await call(
        client, "generate_report_from_dashboard", dashboard_id=str(scene.dashboard.id), name="M"
    )
    assert generated["report"]["dashboard_id"] == str(scene.dashboard.id)
    assert generated["version"]["dashboard_version_id"] == str(scene.dashboard_version.id)
    again = await call(
        client, "generate_report_from_dashboard", dashboard_id=str(scene.dashboard.id), name="M"
    )
    assert again["versions"] == ["1.0.0", "1.1.0"]
    listed = await call(
        client,
        "list_reports",
        project_id=str(scene.project.id),
        dashboard_id=str(scene.dashboard.id),
    )
    assert len(listed) == 1
    events = [e for e in await published(container) if e.type is EventType.REPORT_VERSION_CREATED]
    assert [e.payload["version"] for e in events] == ["1.0.0", "1.1.0"]


async def test_a_template_is_created_listed_and_filled(client: Client, scene: Scene) -> None:
    template = await call(
        client,
        "create_template",
        project_id=str(scene.project.id),
        name="Brief",
        kind="report",
        slots=[{"name": "gap", "description": "The headline gap"}],
        content=blocks(heading("Gap"), {"type": "widget", "slot": "gap"}),
    )
    listed = await call(client, "list_templates", project_id=str(scene.project.id))
    assert [item["id"] for item in listed] == [template["id"]]

    filled = await call(
        client,
        "create_report",
        project_id=str(scene.project.id),
        name="Brief 2024",
        content={"slots": {"gap": str(scene.value.id)}},
        template_id=template["id"],
        session_id=str(scene.session.id),
    )
    assert filled["version"]["template_id"] == template["id"]
    assert filled["version"]["content"]["blocks"][1]["widget_id"] == str(scene.value.id)
