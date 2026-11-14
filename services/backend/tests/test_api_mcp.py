"""The MCP tools of projects, sources, sessions, pipelines and widgets."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Implementation

from ada.composition import create_container
from ada.config import Settings
from ada.core.models.errors import Unavailable
from ada.entrypoints.mcp import actor
from ada.entrypoints.mcp.server import create_mcp
from memory import memory_adapters
from test_api_support import Overrides, Seen

pytestmark = pytest.mark.anyio

AGENT = {"kind": "external_agent", "name": "claude-code"}

WAVE_1_TOOLS = {
    "list_projects",
    "create_project",
    "register_source",
    "list_sources",
    "refresh_source",
    "update_source",
    "create_session",
    "add_source_operator",
    "add_transform",
    "get_lineage",
    "preview_operator",
    "create_widget",
    "list_session_widgets",
}


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


@pytest.fixture
async def client(seen: Seen) -> AsyncIterator[Client]:
    info = Implementation(name="claude-code", version="2.0")
    async with Client(create_mcp(seen.container), client_info=info) as client:
        yield client


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    content = result.structured_content
    # Tools that return a list wrap it, since structured content must be an object.
    return content["result"] if set(content) == {"result"} else content


@pytest.fixture
async def project(client: Client) -> dict[str, Any]:
    return await call(client, "create_project", name="Wellbeing")


@pytest.fixture
async def source(client: Client, project: dict[str, Any]) -> dict[str, Any]:
    return await call(
        client,
        "register_source",
        project_id=project["id"],
        name="Sotkanet",
        address="https://example.test/data.csv",
    )


@pytest.fixture
async def source_operator(
    client: Client, project: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    return await call(
        client, "add_source_operator", project_id=project["id"], data_source_id=source["id"]
    )


@pytest.fixture
async def session(client: Client, project: dict[str, Any]) -> dict[str, Any]:
    return await call(client, "create_session", project_id=project["id"], title="Look")


# Tool list and schemas


async def test_every_wave_1_tool_is_served(client: Client) -> None:
    names = {tool.name for tool in await client.list_tools()}
    assert WAVE_1_TOOLS <= names


async def test_tool_names_are_snake_case_verbs(client: Client) -> None:
    wave_1 = {"list", "create", "register", "update", "refresh", "add", "get", "preview", "system"}
    verbs = wave_1 | {"pin", "edit", "set", "show", "generate", "check"}
    for tool in await client.list_tools():
        assert tool.name == tool.name.lower()
        assert tool.name.split("_")[0] in verbs


async def test_schemas_expose_no_injected_parameters(client: Client) -> None:
    injected = {"service", "projects", "pipelines", "sessions", "widgets", "runs", "dispatcher"}
    for tool in await client.list_tools():
        properties = set(tool.input_schema.get("properties", {}))
        assert not properties & injected, tool.name


async def test_tools_that_create_in_a_session_take_session_id_and_note(client: Client) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}
    for name in ("add_source_operator", "add_transform", "create_widget"):
        properties = tools[name].input_schema["properties"]
        assert {"session_id", "note"} <= set(properties), name
        required = set(tools[name].input_schema.get("required", []))
        assert not required & {"session_id", "note"}, name


async def test_tools_are_documented_for_an_agent(client: Client) -> None:
    for tool in await client.list_tools():
        assert tool.description and len(tool.description) > 40, tool.name


async def test_create_widget_takes_no_data(client: Client) -> None:
    tools = {tool.name: tool for tool in await client.list_tools()}
    properties = set(tools["create_widget"].input_schema["properties"])
    assert properties == {"operator_id", "type", "title", "spec", "session_id", "note"}


# Projects and sessions


async def test_projects_are_created_and_listed(client: Client) -> None:
    assert await call(client, "list_projects") == []
    created = await call(client, "create_project", name="Wellbeing")
    assert created["name"] == "Wellbeing"
    assert created["revision"] == 1
    assert await call(client, "list_projects") == [created]


async def test_a_session_is_created(client: Client, project: dict[str, Any]) -> None:
    session = await call(client, "create_session", project_id=project["id"], title="Look")
    assert session["title"] == "Look"
    assert session["project_id"] == project["id"]


async def test_a_session_in_an_unknown_project_is_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "create_session", project_id=str(uuid7()), title="x")


async def test_a_blank_project_name_is_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="needs a name"):
        await call(client, "create_project", name=" ")


# Sources


async def test_a_source_is_registered_and_listed(
    client: Client, project: dict[str, Any], source: dict[str, Any]
) -> None:
    assert source["access_kind"] == "url"
    assert source["format"] == "csv"
    assert await call(client, "list_sources", project_id=project["id"]) == [source]


async def test_a_changed_address_is_fetched_again(
    client: Client, seen: Seen, source: dict[str, Any]
) -> None:
    renamed = await call(
        client, "update_source", source_id=source["id"], expected_revision=1, name="Renamed"
    )
    assert renamed["revision"] == 2
    assert (await seen.dispatcher()).refreshes == []

    moved = await call(
        client,
        "update_source",
        source_id=source["id"],
        expected_revision=2,
        address="https://example.test/other.csv",
    )
    assert moved["address"] == "https://example.test/other.csv"
    refreshes = (await seen.dispatcher()).refreshes
    assert [(str(id), force) for id, force in refreshes] == [(source["id"], True)]


async def test_an_update_from_a_stale_revision_queues_nothing(
    client: Client, seen: Seen, source: dict[str, Any]
) -> None:
    with pytest.raises(ToolError, match="revision"):
        await call(
            client,
            "update_source",
            source_id=source["id"],
            expected_revision=7,
            address="https://example.test/other.csv",
        )
    assert (await seen.dispatcher()).refreshes == []


async def test_a_request_source_is_registered_with_options_and_freshness(
    client: Client, project: dict[str, Any]
) -> None:
    source = await call(
        client,
        "register_source",
        project_id=project["id"],
        name="Statfin",
        address="https://example.test/api",
        access_kind="request",
        format="json",
        options={"method": "POST", "body": {"query": []}},
        freshness={"kind": "ttl", "ttl_seconds": 3600},
    )
    assert source["access_kind"] == "request"
    assert source["options"]["method"] == "POST"
    assert source["freshness"]["ttl_seconds"] == 3600


async def test_sources_of_an_unknown_project_are_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "list_sources", project_id=str(uuid7()))
    with pytest.raises(ToolError, match="not found"):
        await call(
            client, "register_source", project_id=str(uuid7()), name="x", address="https://x.test"
        )


async def test_an_invalid_source_format_is_rejected(
    client: Client, project: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        await call(
            client,
            "register_source",
            project_id=project["id"],
            name="x",
            address="https://x.test",
            format="xml",
        )


async def test_refreshing_a_source_queues_it(
    client: Client, seen: Seen, source: dict[str, Any]
) -> None:
    result = await call(client, "refresh_source", source_id=source["id"], force=True)
    assert result["status"] == "queued"
    assert result["data_source_id"] == source["id"]
    refreshes = (await seen.dispatcher()).refreshes
    assert [(str(id), force) for id, force in refreshes] == [(source["id"], True)]


async def test_refreshing_an_unknown_source_is_an_error(client: Client, seen: Seen) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "refresh_source", source_id=str(uuid7()))
    assert (await seen.dispatcher()).refreshes == []


async def test_a_refresh_that_cannot_be_queued_says_to_retry_later(
    client: Client, seen: Seen, source: dict[str, Any]
) -> None:
    async def unreachable(data_source_id: UUID, force: bool = False) -> None:
        raise Unavailable("The task queue could not be reached: connection refused")

    (await seen.dispatcher()).refresh_source = unreachable  # type: ignore[method-assign]
    with pytest.raises(ToolError, match=r"could not be reached: .*try again later"):
        await call(client, "refresh_source", source_id=source["id"])


# Pipelines


async def test_a_source_operator_is_added_and_recorded_in_the_session(
    client: Client,
    seen: Seen,
    project: dict[str, Any],
    session: dict[str, Any],
    source: dict[str, Any],
) -> None:
    operator = await call(
        client,
        "add_source_operator",
        project_id=project["id"],
        data_source_id=source["id"],
        session_id=session["id"],
        note="Starting from the raw data",
    )
    assert operator["kind"] == "source"
    assert operator["created_by"] == AGENT

    [entry] = await seen.entries(UUID(session["id"]))
    assert entry.kind == "operator"
    assert entry.ref == operator["id"]
    assert entry.text == "Starting from the raw data"
    assert entry.actor.model_dump() == {"kind": "external_agent", "name": "claude-code"}
    created, event = await seen.events()
    assert created.type == "session.created"
    assert event.type == "session.entry_added"
    assert event.payload == {"session_id": session["id"], "entry_id": str(entry.id)}


async def test_an_operator_added_without_a_session_leaves_no_entry(
    client: Client, seen: Seen, session: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    assert await seen.entries(UUID(session["id"])) == []
    assert [event.type for event in await seen.events()] == ["session.created"]


async def test_a_transform_is_added_over_inputs_and_recorded(
    client: Client,
    seen: Seen,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    operator = await call(
        client,
        "add_transform",
        project_id=project["id"],
        sql="SELECT region FROM input_0",
        inputs=[source_operator["id"]],
        session_id=session["id"],
        note="Only the regions",
    )
    assert operator["kind"] == "transform"
    assert operator["inputs"] == [source_operator["id"]]
    [entry] = await seen.entries(UUID(session["id"]))
    assert (entry.kind, entry.ref, entry.text) == ("operator", operator["id"], "Only the regions")


async def test_a_transform_takes_roles(
    client: Client, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    operator = await call(
        client,
        "add_transform",
        project_id=project["id"],
        sql="SELECT region, value FROM input_0",
        inputs=[source_operator["id"]],
        roles={"measures": [{"value": "value"}]},
        materialize=True,
    )
    assert operator["output"]["roles"]["measures"][0]["value"] == "value"


async def test_an_invalid_transform_is_an_error(
    client: Client, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    with pytest.raises(ToolError, match="Not a query"):
        await call(
            client,
            "add_transform",
            project_id=project["id"],
            sql="DROP TABLE x",
            inputs=[source_operator["id"]],
        )


async def test_an_operator_is_not_recorded_in_a_session_of_another_project(
    client: Client, source_operator: dict[str, Any], project: dict[str, Any]
) -> None:
    other = await call(client, "create_project", name="Other")
    elsewhere = await call(client, "create_session", project_id=other["id"], title="Elsewhere")
    with pytest.raises(ToolError, match="another project"):
        await call(
            client,
            "add_transform",
            project_id=project["id"],
            sql="SELECT 1",
            inputs=[source_operator["id"]],
            session_id=elsewhere["id"],
        )


async def test_lineage_lists_inputs_first(
    client: Client, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    transform = await call(
        client,
        "add_transform",
        project_id=project["id"],
        sql="SELECT * FROM input_0",
        inputs=[source_operator["id"]],
    )
    lineage = await call(client, "get_lineage", operator_id=transform["id"])
    assert [operator["id"] for operator in lineage] == [source_operator["id"], transform["id"]]


async def test_lineage_of_an_unknown_operator_is_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "get_lineage", operator_id="op_missing")


async def test_a_preview_returns_columns_and_a_few_rows(
    client: Client, seen: Seen, source_operator: dict[str, Any]
) -> None:
    preview = await call(client, "preview_operator", operator_id=source_operator["id"], limit=1)
    assert preview["operator_id"] == source_operator["id"]
    assert [column["name"] for column in preview["rows"]["columns"]] == ["region", "value"]
    assert preview["rows"]["rows"] == [["north", 1.5]]
    assert preview["rows"]["truncated"] is True
    [(run_id, operator_id, limit)] = seen.results.reads
    assert (str(run_id), operator_id, limit) == (preview["run_id"], source_operator["id"], 1)


@pytest.mark.parametrize("limit", [0, 101])
async def test_a_preview_cannot_be_large(
    client: Client, source_operator: dict[str, Any], limit: int
) -> None:
    with pytest.raises(ToolError):
        await call(client, "preview_operator", operator_id=source_operator["id"], limit=limit)


async def test_previewing_an_unknown_operator_is_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "preview_operator", operator_id="op_missing")


# Widgets


async def test_a_widget_in_a_session_is_created_with_its_url(
    client: Client,
    seen: Seen,
    project: dict[str, Any],
    session: dict[str, Any],
    source_operator: dict[str, Any],
) -> None:
    created = await call(
        client,
        "create_widget",
        operator_id=source_operator["id"],
        type="table",
        title="Regions",
        spec={"limit": 5},
        session_id=session["id"],
        note="The regions side by side",
    )
    widget = created["widget"]
    assert widget["operator_id"] == source_operator["id"]
    assert widget["project_id"] == project["id"]
    assert widget["session_id"] == session["id"]
    assert widget["spec"] == {"limit": 5}
    assert widget["note"] == "The regions side by side"
    assert widget["created_by"] == AGENT
    assert created["url"] == (
        f"/projects/{project['id']}/sessions/{session['id']}?widget={widget['id']}"
    )

    [entry] = await seen.entries(UUID(session["id"]))
    assert (entry.kind, entry.ref, entry.text) == (
        "widget",
        widget["id"],
        "The regions side by side",
    )
    assert entry.actor.name == "claude-code"
    assert [event.type for event in await seen.events()] == [
        "session.created",
        "widget.created",
        "session.entry_added",
    ]


async def test_a_widget_without_a_session_has_its_own_page(
    client: Client, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    created = await call(
        client, "create_widget", operator_id=source_operator["id"], type="value", title="Total"
    )
    assert created["widget"]["session_id"] is None
    assert created["url"] == f"/projects/{project['id']}/widgets/{created['widget']['id']}"


async def test_a_widget_of_an_unknown_operator_or_session_is_an_error(
    client: Client, source_operator: dict[str, Any]
) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "create_widget", operator_id="op_missing", type="table", title="t")
    with pytest.raises(ToolError, match="not found"):
        await call(
            client,
            "create_widget",
            operator_id=source_operator["id"],
            type="table",
            title="t",
            session_id=str(uuid7()),
        )


async def test_session_widgets_are_listed_with_their_urls(
    client: Client, session: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    assert await call(client, "list_session_widgets", session_id=session["id"]) == []
    created = await call(
        client,
        "create_widget",
        operator_id=source_operator["id"],
        type="table",
        title="Regions",
        session_id=session["id"],
    )
    assert await call(client, "list_session_widgets", session_id=session["id"]) == [created]


async def test_listing_widgets_of_an_unknown_session_is_an_error(client: Client) -> None:
    with pytest.raises(ToolError, match="not found"):
        await call(client, "list_session_widgets", session_id=str(uuid7()))


# Who is calling


async def test_the_actor_is_the_client_the_host_reported(
    client: Client, project: dict[str, Any], source_operator: dict[str, Any]
) -> None:
    assert source_operator["created_by"] == AGENT


@pytest.mark.parametrize(
    "client_params",
    [
        None,
        SimpleNamespace(client_info=None),
        SimpleNamespace(client_info=Implementation(name=" ", version="1")),
    ],
)
def test_without_a_client_name_the_actor_is_an_unknown_client(client_params: object) -> None:
    context = SimpleNamespace(session=SimpleNamespace(client_params=client_params))
    with patch.object(actor, "get_context", return_value=context):
        assert actor.calling_agent().model_dump() == {
            "kind": "external_agent",
            "name": "unknown client",
        }


def test_outside_a_request_the_actor_is_an_unknown_client() -> None:
    with patch.object(actor, "get_context", side_effect=RuntimeError("No active context")):
        assert actor.calling_agent().name == "unknown client"
