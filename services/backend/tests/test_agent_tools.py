"""The in-platform agent's tools: the MCP server served in process, acting as the agent.
Who the agent is comes from the worker's own context, never from what a client reports."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client
from mcp.types import Implementation

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.ports.agents import ToolCallFailed
from ada.entrypoints.mcp.agent import CLIENT, LEFT_OUT, InProcessToolbox
from ada.entrypoints.mcp.server import create_mcp
from memory import memory_adapters
from test_api_support import Overrides, Seen

pytestmark = pytest.mark.anyio

AGENT = Actor(kind=ActorKind.AGENT, name="gemini/flash")


@pytest.fixture
async def seen(unreachable_settings: Settings) -> AsyncIterator[Seen]:
    overrides = Overrides()
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), overrides
    )
    try:
        yield Seen(container, overrides)
    finally:
        await container.close()


async def setup(client: Client) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = (await client.call_tool("create_project", {"name": "P"})).structured_content
    assert project is not None
    session = (
        await client.call_tool("create_session", {"project_id": project["id"], "title": "S"})
    ).structured_content
    source = (
        await client.call_tool(
            "register_source",
            {"project_id": project["id"], "name": "Sotkanet", "address": "https://x.test"},
        )
    ).structured_content
    assert session is not None and source is not None
    return project, session, source


async def test_the_agent_gets_every_tool_but_those_it_cannot_use(seen: Seen) -> None:
    async with Client(create_mcp(seen.container)) as client:
        everything = {tool.name for tool in await client.list_tools()}
        _, session, _ = await setup(client)

    async with InProcessToolbox(seen.container).connect(AGENT, session["id"]) as tools:
        names = {spec.name for spec in tools.specs()}

    assert names == everything - LEFT_OUT
    assert {"list_pipelines", "create_widget", "pin_widget"} <= names
    assert "get_widget_data" not in names
    assert all(spec.input_schema.get("type") == "object" for spec in tools.specs())


async def test_tool_calls_act_as_the_agent_in_its_session(seen: Seen) -> None:
    async with Client(create_mcp(seen.container)) as client:
        project, session, source = await setup(client)

    async with InProcessToolbox(seen.container).connect(AGENT, session["id"]) as tools:
        operator = await tools.call(
            "add_source_operator",
            {"project_id": project["id"], "data_source_id": source["id"], "note": "why"},
        )
        listed = await tools.call("list_pipelines", {"project_id": project["id"]})

    [entry] = await seen.entries(UUID(session["id"]))
    assert (entry.kind, entry.ref, entry.text) == ("operator", operator["id"], "why")
    assert entry.actor == AGENT
    # A list comes unwrapped, as the tool returned it.
    assert [p["operator_id"] for p in listed] == [operator["id"]]


async def test_a_refused_call_is_a_tool_call_failure_with_the_tool_s_message(seen: Seen) -> None:
    async with Client(create_mcp(seen.container)) as client:
        project, session, _ = await setup(client)

    async with InProcessToolbox(seen.container).connect(AGENT, session["id"]) as tools:
        with pytest.raises(ToolCallFailed, match="Not a query"):
            await tools.call(
                "add_transform", {"project_id": project["id"], "sql": "nope", "inputs": []}
            )
        with pytest.raises(ToolCallFailed, match="no tool"):
            await tools.call("get_widget_data", {"widget_id": str(uuid7())})


async def test_an_outside_client_cannot_pass_for_the_agent(seen: Seen) -> None:
    # Over MCP, a client may report any name, including the in-process client's.
    async with Client(create_mcp(seen.container), client_info=CLIENT) as client:
        project, session, source = await setup(client)
        await client.call_tool(
            "add_source_operator",
            {
                "project_id": project["id"],
                "data_source_id": source["id"],
                "session_id": session["id"],
            },
        )
    impostor = Implementation(name="gemini/flash", version="1")
    async with Client(create_mcp(seen.container), client_info=impostor) as client:
        await client.call_tool(
            "create_widget",
            {
                "operator_id": (await seen.entries(UUID(session["id"])))[0].ref,
                "type": "table",
                "title": "T",
                "session_id": session["id"],
            },
        )

    actors = [entry.actor for entry in await seen.entries(UUID(session["id"]))]
    assert actors == [
        Actor(kind=ActorKind.EXTERNAL_AGENT, name=CLIENT.name),
        Actor(kind=ActorKind.EXTERNAL_AGENT, name="gemini/flash"),
    ]
