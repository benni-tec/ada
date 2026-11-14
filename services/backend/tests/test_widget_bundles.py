"""The built widgets: served to the frontend over REST, and to MCP hosts as MCP App
resources that create_widget links to."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client

from ada.composition import create_container
from ada.config import Settings
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from memory import memory_adapters
from test_api_support import Overrides

BUNDLE = "<!doctype html><title>Table</title>"


@pytest.fixture
def settings(unreachable_settings: Settings, tmp_path: Path) -> Settings:
    widgets = tmp_path / "widgets"
    widgets.mkdir()
    (widgets / "table.html").write_text(BUNDLE)
    (widgets / "any.html").write_text("<!doctype html><title>Widget</title>")
    (tmp_path / "secret.html").write_text("not a widget")
    return unreachable_settings.model_copy(update={"widgets_dir": widgets})


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, *memory_adapters())) as client:
        yield client


def test_a_built_widget_is_served_as_html(client: TestClient) -> None:
    response = client.get("/api/widget-bundles/table.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == BUNDLE


@pytest.mark.parametrize(
    "path",
    [
        "/api/widget-bundles/map.html",
        "/api/widget-bundles/..%2Fsecret.html",
        "/api/widget-bundles/%2E%2E.html",
        "/api/widget-bundles/Table.html",
    ],
)
def test_only_built_widgets_are_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.fixture
async def mcp(settings: Settings) -> AsyncIterator[Client]:
    overrides = Overrides()
    container = create_container(settings, FastapiProvider(), *memory_adapters(), overrides)
    try:
        async with Client(create_mcp(container, settings.widgets_dir)) as client:
            yield client
    finally:
        await container.close()


@pytest.mark.anyio
async def test_every_widget_is_an_mcp_app_resource(mcp: Client) -> None:
    resources = {str(resource.uri): resource for resource in await mcp.list_resources()}
    assert set(resources) == {"ui://ada/widgets/table.html", "ui://ada/widgets/any.html"}
    assert resources["ui://ada/widgets/table.html"].mime_type == "text/html;profile=mcp-app"
    [content] = await mcp.read_resource("ui://ada/widgets/table.html")
    assert getattr(content, "text", None) == BUNDLE


@pytest.mark.anyio
async def test_create_widget_is_rendered_by_the_bundle_of_every_type(mcp: Client) -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    meta: dict[str, Any] = tools["create_widget"].meta or {}
    assert meta["ui"]["resourceUri"] == "ui://ada/widgets/any.html"


@pytest.mark.anyio
async def test_the_widget_reads_its_data_through_a_tool(mcp: Client) -> None:
    async def call(tool: str, **arguments: Any) -> Any:
        return (await mcp.call_tool(tool, arguments)).structured_content

    project = await call("create_project", name="P")
    source = await call(
        "register_source", project_id=project["id"], name="S", address="https://example.test/d.csv"
    )
    operator = await call(
        "add_source_operator", project_id=project["id"], data_source_id=source["id"]
    )
    view = await call("create_widget", operator_id=operator["id"], type="table", title="T")
    data = await call("get_widget_data", widget_id=view["widget"]["id"], limit=1)
    assert data["widget_id"] == view["widget"]["id"]
    assert data["rows"] == [["north", 1.5]]
    assert data["truncated"] is True
