"""Exercise output bounds through MCP serialization, without external services."""

import json
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope

from ada.config import Settings
from ada.core.models.analysis import Rows
from ada.core.models.schema import Column, ColumnType
from ada.core.services.ports.exploration import ExplorationService, Explored
from ada.entrypoints.mcp.bounds import MAX_RESULT_BYTES
from api_support import FakeWeb, call, mcp_client
from fakes import FakeExplorer


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["preview_operator", "query_operator", "extract_table"])
async def test_model_rows_are_bounded_without_changing_service_data(
    unreachable_settings: Settings, tool: str
) -> None:
    text = "ä“" * 10_000
    rows = Rows(
        columns=(
            Column(name="text", type=ColumnType.TEXT),
            Column(name="count", type=ColumnType.INTEGER),
            Column(name="missing", type=ColumnType.TEXT),
        ),
        rows=tuple((text, i, None) for i in range(100)),
    )
    exploration = AsyncMock(spec=ExplorationService)
    exploration.query.return_value = Explored(rows=rows, run_id=None)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: exploration, provides=ExplorationService)
    explorer = FakeExplorer(
        rows=[dict(zip(("text", "count", "missing"), row, strict=True)) for row in rows.rows]
    )
    async with mcp_client(unreachable_settings, provider, FakeWeb(explorer=explorer)) as (
        client,
        seen,
    ):
        seen.results.rows = rows
        project = await call(client, "create_project", name="Bounds")
        session = await call(client, "create_session", project_id=project["id"], title="Bounds")
        arguments = {"session_id": session["id"]}
        if tool == "extract_table":
            arguments.update(
                project_id=project["id"],
                url="https://example.test/page",
                instruction="Read the table",
                columns=["text", "count", "missing"],
            )
        else:
            operator = await call(
                client,
                "add_transform",
                project_id=project["id"],
                session_id=session["id"],
                sql="SELECT 1",
                inputs=[],
            )
            arguments.update(operator_id=operator["id"], limit=100)
            if tool == "query_operator":
                arguments["select"] = "*"
        result = await client.call_tool(tool, arguments)

    data = result.structured_content
    assert data is not None
    assert len(json.dumps(data, indent=2).encode()) <= MAX_RESULT_BYTES
    assert all(len(block.text.encode()) <= MAX_RESULT_BYTES for block in result.content)
    table = data["rows"] if tool == "preview_operator" else data
    assert table["truncated"] is True
    assert 0 < len(table["rows"]) < 100
    assert table["dropped_rows"] == 100 - len(table["rows"])
    first = table["rows"][0]
    cells = list(first.values()) if isinstance(first, dict) else first
    assert cells == [text[:300] + "…[+19700 chars]", 0, None]
    assert rows.rows[0][0] == text
    assert explorer.extraction.rows[0]["text"] == text
