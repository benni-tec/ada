"""The project's pipelines: what "Add widget" offers and list_pipelines tells an agent."""

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid7

import pytest
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError

import factories
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryStore,
)
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import PLATFORM
from ada.core.models.operators import Operator, OperatorKind
from ada.core.services.pipelines.listing import sql_name
from ada.core.services.pipelines.service import Pipelines
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from memory import memory_adapters
from test_api_support import Overrides, Seen

pytestmark = pytest.mark.anyio


class World:
    """Operators stored directly, each a second later than the one before."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.project = factories.project()
        self.store.projects[self.project.id] = self.project
        self.ticks = 0

    def source(self, name: str) -> Operator:
        source = factories.data_source(self.project.id, name=name)
        self.store.data_sources[source.id] = source
        return self._add(OperatorKind.SOURCE, {"data_source_id": str(source.id)})

    def transform(self, sql: str, *inputs: Operator) -> Operator:
        return self._add(OperatorKind.TRANSFORM, {"sql": sql}, *inputs)

    def input(self, name: str, default: Operator) -> Operator:
        return self._add(OperatorKind.INPUT, {"name": name}, default)

    def _add(self, kind: OperatorKind, params: dict[str, Any], *inputs: Operator) -> Operator:
        self.ticks += 1
        operator = factories.operator(
            self.project.id,
            kind,
            params,
            inputs=tuple(i.id for i in inputs),
            created_at=factories.NOW + timedelta(seconds=self.ticks),
        )
        self.store.operators[operator.id] = operator
        return operator

    async def pipelines(self) -> Any:
        service = Pipelines(
            MemoryOperatorRepository(self.store),
            MemoryDataSourceRepository(self.store),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        return await service.pipelines(self.project.id)


async def test_only_operators_nothing_builds_on_are_pipelines_newest_first() -> None:
    world = World()
    screening = world.source("Sotkanet screening")
    regions = world.source("Regions")
    left = world.transform("-- Screening by county\nSELECT * FROM input_0", screening)
    right = world.transform("SELECT region, value FROM input_0 WHERE value > 1", screening)
    # A diamond: both sides read the screening source.
    joined = world.transform(
        "SELECT l.region, l.value, r.value AS previous FROM input_0 AS l "
        "JOIN input_1 AS r ON l.region = r.region",
        left,
        right,
    )
    baseline = world.input("baseline", regions)
    unused = world.source("Boundaries")

    pipelines = await world.pipelines()

    assert [p.operator_id for p in pipelines] == [unused.id, baseline.id, joined.id]
    by_id = {p.operator_id: p for p in pipelines}
    diamond = by_id[joined.id]
    assert [(str(s.data_source_id), s.name) for s in diamond.sources] == [
        (screening.params["data_source_id"], "Sotkanet screening")
    ]
    assert diamond.kind is OperatorKind.TRANSFORM
    assert diamond.name == "SELECT l.region, l.value, r.value AS previous FROM input_0…"
    assert diamond.output == joined.output
    assert diamond.created_at == joined.created_at
    assert by_id[baseline.id].name == "baseline"
    assert [s.name for s in by_id[baseline.id].sources] == ["Regions"]
    assert by_id[unused.id].name == "Boundaries"
    assert by_id[unused.id].kind is OperatorKind.SOURCE


async def test_an_alert_filter_is_not_a_pipeline_and_hides_nothing() -> None:
    world = World()
    source = world.source("Sotkanet")
    world.store.operators[source.id] = source.model_copy(update={"created_by": PLATFORM})
    measure = world.transform("-- Screening coverage\nSELECT 1", source)
    alerting = world.transform("SELECT * FROM measure WHERE value < 80", measure)
    world.store.operators[alerting.id] = alerting.model_copy(update={"created_by": PLATFORM})

    pipelines = await world.pipelines()

    assert [p.operator_id for p in pipelines] == [measure.id]


async def test_a_project_without_operators_has_no_pipelines() -> None:
    assert await World().pipelines() == []


def test_sql_is_named_by_its_leading_comment_or_its_first_words() -> None:
    assert sql_name("-- Participation by county\n-- (latest year)\nSELECT 1") == (
        "Participation by county (latest year)"
    )
    assert sql_name("  SELECT   region,\n  value FROM input_0  ") == (
        "SELECT region, value FROM input_0"
    )
    long = "SELECT " + ", ".join(f"column_{i}" for i in range(20)) + " FROM input_0"
    assert len(sql_name(long)) <= 60
    assert sql_name(long).endswith("…")


# REST and MCP


@pytest.fixture
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    app = create_app(unreachable_settings, *memory_adapters(), Overrides())
    with TestClient(app) as client:
        yield client


def test_the_pipelines_route_lists_the_project_s_pipelines(client: TestClient) -> None:
    project = client.post("/api/projects", json={"name": "P"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={
            "name": "Sotkanet",
            "access_kind": "url",
            "address": "https://x.test",
            "format": "csv",
        },
    ).json()
    operator = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "source", "data_source_id": source["id"]},
    ).json()
    transform = client.post(
        f"/api/projects/{project['id']}/operators",
        json={"kind": "transform", "sql": "SELECT * FROM input_0", "inputs": [operator["id"]]},
    ).json()

    response = client.get(f"/api/projects/{project['id']}/pipelines")

    assert response.status_code == 200
    assert response.json() == [
        {
            "operator_id": transform["id"],
            "name": "SELECT * FROM input_0",
            "kind": "transform",
            "sources": [{"data_source_id": source["id"], "name": "Sotkanet"}],
            "output": transform["output"],
            "created_at": transform["created_at"],
        }
    ]
    assert client.get(f"/api/projects/{uuid7()}/pipelines").status_code == 404


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


async def test_list_pipelines_is_an_mcp_tool(seen: Seen) -> None:
    async with Client(create_mcp(seen.container)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "list_pipelines" in tools
        assert len(tools["list_pipelines"].description or "") > 80

        project = (await client.call_tool("create_project", {"name": "P"})).structured_content
        assert project is not None
        source = (
            await client.call_tool(
                "register_source",
                {"project_id": project["id"], "name": "Sotkanet", "address": "https://x.test"},
            )
        ).structured_content
        assert source is not None
        await client.call_tool(
            "add_source_operator", {"project_id": project["id"], "data_source_id": source["id"]}
        )

        listed = await client.call_tool("list_pipelines", {"project_id": project["id"]})

        assert listed.structured_content is not None
        [pipeline] = listed.structured_content["result"]
        assert (pipeline["name"], pipeline["kind"]) == ("Sotkanet", "source")
        with pytest.raises(ToolError):
            await client.call_tool("list_pipelines", {"project_id": str(uuid7())})
