from collections.abc import AsyncIterator

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client

from ada.composition import create_container
from ada.config import Settings
from ada.entrypoints.mcp.server import create_mcp
from conftest import UNREACHABLE_HEALTH

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(unreachable_settings: Settings) -> AsyncIterator[Client]:
    container = create_container(unreachable_settings, FastapiProvider())
    try:
        async with Client(create_mcp(container)) as client:
            yield client
    finally:
        await container.close()


async def test_system_status_tool_reports_unreachable_dependencies(client: Client) -> None:
    result = await client.call_tool("system_status")
    assert result.structured_content == UNREACHABLE_HEALTH


async def test_tool_schemas_hide_injected_services(client: Client) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}
    assert tools["system_status"].input_schema.get("properties", {}) == {}
