"""Shared setup for the tests of the REST routes and MCP tools.

The tests of the API surface stand in small fakes for the pipeline, run and source
services, which need DuckDB and the network, and keep everything else real: the other
services, the memory repositories, the event bus and the task dispatcher.

Building an app or an MCP server takes a while (every tool's schema is generated), so a
module builds one and its tests share it: each test works in a project of its own and
reads only that project's events. This module holds helpers only.
"""

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid7

from dishka import AsyncContainer, Provider, Scope, provide
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from mcp.types import Implementation

from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import MemoryStore
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import Actor
from ada.core.models.analysis import Rows
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.events import Event
from ada.core.models.operators import (
    Operator,
    OperatorId,
    OperatorKind,
    SourceParams,
    operator_identity,
)
from ada.core.models.pipelines import Pipeline
from ada.core.models.runs import Run, Snapshot
from ada.core.models.schema import Column, ColumnType, Roles, Schema
from ada.core.models.sessions import SessionEntry
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessPolicy,
    Provenance,
    RefreshResult,
)
from ada.core.models.time import TimeRange
from ada.core.ports.repositories import (
    DataSourceRepository,
    OperatorRepository,
    RunRepository,
    SessionRepository,
    SnapshotRepository,
)
from ada.core.ports.system import Clock
from ada.core.ports.tasks import TaskDispatcher
from ada.core.ports.web import PageReader, WebSearch
from ada.core.services.pipelines import listing
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.http.app import create_app
from ada.entrypoints.mcp.server import create_mcp
from fakes import FakePageReader, FakeWebSearch, FixedClock
from memory import memory_adapters

COLUMNS = (
    Column(name="region", type=ColumnType.TEXT),
    Column(name="value", type=ColumnType.NUMBER),
)


@dataclass
class Results:
    """What the fake run service reads, and what it was asked."""

    rows: Rows = field(
        default_factory=lambda: Rows(columns=COLUMNS, rows=(("north", 1.5), ("south", 2.5)))
    )
    reads: list[tuple[Id, OperatorId, int]] = field(default_factory=list)


class FakePipelines(PipelineService):
    """Adds operators the way the real service does, minus schema derivation."""

    def __init__(self, operators: OperatorRepository, sources: DataSourceRepository) -> None:
        self.operators = operators
        self.sources = sources

    async def _add(
        self,
        project_id: Id,
        kind: OperatorKind,
        params: dict[str, object],
        inputs: Sequence[OperatorId],
        output: Schema,
        actor: Actor,
    ) -> Operator:
        return await self.operators.add(
            Operator(
                id=operator_identity(project_id, kind, params, inputs),
                project_id=project_id,
                kind=kind,
                params=params,
                inputs=tuple(inputs),
                output=output,
                materializing=kind is OperatorKind.SOURCE,
                created_by=actor,
                created_at=FixedClock().now(),
            )
        )

    async def add_source(self, project_id: Id, data_source_id: Id, actor: Actor) -> Operator:
        await self.sources.get(data_source_id)
        params = SourceParams(data_source_id=data_source_id).model_dump(mode="json")
        return await self._add(
            project_id, OperatorKind.SOURCE, params, (), Schema(columns=COLUMNS), actor
        )

    async def add_transform(
        self,
        project_id: Id,
        sql: str,
        inputs: Sequence[OperatorId],
        actor: Actor,
        roles: Roles | None = None,
        materialize: bool = False,
    ) -> Operator:
        if "select" not in sql.lower():
            raise Invalid(f"Not a query: {sql}")
        for input_id in inputs:
            await self.operators.get(input_id)
        schema = Schema(columns=COLUMNS, roles=roles or Roles(), derived=True)
        return await self._add(
            project_id, OperatorKind.TRANSFORM, {"sql": sql}, inputs, schema, actor
        )

    async def add_input(
        self, project_id: Id, name: str, output: Schema, default: OperatorId, actor: Actor
    ) -> Operator:
        return await self._add(
            project_id, OperatorKind.INPUT, {"name": name}, (default,), output, actor
        )

    async def get(self, id: OperatorId) -> Operator:
        return await self.operators.get(id)

    async def lineage(self, id: OperatorId) -> Sequence[Operator]:
        return await self.operators.upstream(id)

    async def pipelines(self, project_id: Id) -> Sequence[Pipeline]:
        names = {source.id: source.name for source in await self.sources.list(project_id)}
        return listing.pipelines(await self.operators.list(project_id), names)


class FakeRuns(RunService):
    def __init__(
        self,
        runs: RunRepository,
        snapshots: SnapshotRepository,
        results: Results,
        clock: Clock,
    ) -> None:
        self.runs = runs
        self.snapshots = snapshots
        self.results = results
        self.clock = clock

    async def start(
        self,
        project_id: Id,
        actor: Actor,
        time_range: TimeRange | None = None,
        bindings: dict[str, OperatorId] | None = None,
    ) -> Run:
        run = Run(
            id=uuid7(),
            project_id=project_id,
            time_range=time_range or TimeRange(),
            bindings=bindings or {},
            started_by=actor,
            started_at=self.clock.now(),
        )
        await self.runs.add(run)
        return run

    async def get(self, id: Id) -> Run:
        return await self.runs.get(id)

    async def list(self, project_id: Id, limit: int = 50) -> Sequence[Run]:
        return await self.runs.list(project_id, limit)

    async def snapshot(self, id: Id) -> Snapshot:
        return await self.snapshots.get(id)

    async def execute(self, run_id: Id, operator_id: OperatorId) -> Run:
        return await self.runs.get(run_id)

    async def read(self, run_id: Id, operator_id: OperatorId, limit: int = 1000) -> Rows:
        await self.runs.get(run_id)
        self.results.reads.append((run_id, operator_id, limit))
        rows = self.results.rows
        return Rows(columns=rows.columns, rows=rows.rows[:limit], truncated=len(rows.rows) > limit)


class FakeSources(SourceService):
    def __init__(self, sources: DataSourceRepository, clock: Clock) -> None:
        self.sources = sources
        self.clock = clock

    async def register(
        self,
        project_id: Id,
        name: str,
        access_kind: AccessKind,
        address: str,
        format: DataFormat,
        options: dict | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
        provenance: Provenance | None = None,
    ) -> DataSource:
        source = DataSource(
            id=uuid7(),
            project_id=project_id,
            name=name,
            access_kind=access_kind,
            address=address,
            format=format,
            options=options or {},
            freshness=freshness or FreshnessPolicy(),
            declared_schema=declared_schema,
            provenance=provenance,
            created_at=self.clock.now(),
        )
        await self.sources.add(source)
        return source

    async def get(self, id: Id) -> DataSource:
        return await self.sources.get(id)

    async def list(self, project_id: Id) -> Sequence[DataSource]:
        return await self.sources.list(project_id)

    async def update(
        self,
        id: Id,
        expected_revision: int,
        name: str | None = None,
        address: str | None = None,
        options: dict | None = None,
        freshness: FreshnessPolicy | None = None,
        declared_schema: Schema | None = None,
    ) -> DataSource:
        source = await self.sources.get(id)
        changes = {
            key: value
            for key, value in {
                "name": name,
                "address": address,
                "options": options,
                "freshness": freshness,
                "declared_schema": declared_schema,
            }.items()
            if value is not None
        }
        return await self.sources.update(source.model_copy(update=changes), expected_revision)

    async def refresh(self, id: Id, force: bool = False) -> RefreshResult:
        raise AssertionError("The entrypoints queue refreshes; they never run them")

    async def due(self) -> Sequence[DataSource]:
        return []


class Overrides(Provider):
    """Binds the fakes in place of the other workstreams' services, and a clock that
    stands still."""

    scope = Scope.REQUEST

    def __init__(self) -> None:
        super().__init__()
        self.clock = FixedClock()
        self.results = Results()

    @provide(scope=Scope.APP)
    def clock_(self) -> Clock:
        return self.clock

    @provide(scope=Scope.APP)
    def results_(self) -> Results:
        return self.results

    pipelines = provide(FakePipelines, provides=PipelineService)
    runs = provide(FakeRuns, provides=RunService)
    sources = provide(FakeSources, provides=SourceService)


class FakeWeb(Provider):
    """The web tools' ports on fakes."""

    def __init__(self, search: FakeWebSearch, pages: FakePageReader) -> None:
        super().__init__()
        self.search, self.pages = search, pages

    @provide(scope=Scope.APP)
    def search_(self) -> WebSearch:
        return self.search

    @provide(scope=Scope.APP)
    def pages_(self) -> PageReader:
        return self.pages


@dataclass
class Seen:
    """What the code under test left behind, read from the container it ran in."""

    container: AsyncContainer
    overrides: Overrides

    @property
    def clock(self) -> FixedClock:
        return self.overrides.clock

    @property
    def results(self) -> Results:
        return self.overrides.results

    async def events(self, project_id: Any = None) -> list[Event]:
        """What was published, of one project if given."""
        published = (await self.container.get(MemoryEventBus)).published
        return [e for e in published if project_id is None or str(e.project_id) == str(project_id)]

    async def dispatcher(self) -> RecordingTaskDispatcher:
        dispatcher = await self.container.get(TaskDispatcher)
        assert isinstance(dispatcher, RecordingTaskDispatcher)
        return dispatcher

    async def entries(self, session_id: Id) -> Sequence[SessionEntry]:
        async with self.container() as request:
            return await (await request.get(SessionRepository)).entries(session_id)


@contextmanager
def serve(settings: Settings, *providers: Provider) -> Iterator[TestClient]:
    """The app on the memory adapters, with `providers` overriding the composition root's."""
    with TestClient(create_app(settings, *memory_adapters(), *providers)) as client:
        yield client


def resolve[T](client: TestClient, port: type[T]) -> T:
    """An application-scoped object of the app under test, e.g. the event bus."""
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    return client.portal.call(container.get, port)


def events(client: TestClient, project_id: Any) -> list[Event]:
    published = resolve(client, MemoryEventBus).published
    return [e for e in published if str(e.project_id) == str(project_id)]


def store(client: TestClient) -> MemoryStore:
    return resolve(client, MemoryStore)


def dispatcher(client: TestClient) -> RecordingTaskDispatcher:
    found = resolve(client, TaskDispatcher)
    assert isinstance(found, RecordingTaskDispatcher)
    return found


def send(client: TestClient, method: str, path: str, body: Any = None, ok: int = 200) -> Any:
    """A request to /api that must answer `ok`; returns the body."""
    response = client.request(method, f"/api{path}", json=body)
    assert response.status_code == ok, response.text
    return response.json()


def new_project(client: TestClient, name: str = "Wellbeing") -> dict[str, Any]:
    return send(client, "POST", "/projects", {"name": name}, 201)


@asynccontextmanager
async def mcp_client(
    settings: Settings, *providers: Provider, client_name: str = "claude-code"
) -> AsyncIterator[tuple[Client, Seen]]:
    """An MCP client of the server on the memory adapters, as a host named `client_name`."""
    overrides = Overrides()
    container = create_container(
        settings, FastapiProvider(), *memory_adapters(), overrides, *providers
    )
    info = Implementation(name=client_name, version="2.0")
    try:
        async with Client(create_mcp(container), client_info=info) as client:
            yield client, Seen(container, overrides)
    finally:
        await container.close()


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    result = await client.call_tool(tool, arguments)
    assert result.structured_content is not None
    content = result.structured_content
    # Tools that return a list wrap it, since structured content must be an object.
    return content["result"] if set(content) == {"result"} else content
