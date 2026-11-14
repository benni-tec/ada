"""Sources: registering, refreshing by freshness policy, the HTTP readers, shaping an answer
into a table, and the example registrations against their recorded answers."""

import asyncio
import csv
import gzip
import io
import json
import socket
import time
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid7

import httpx
import pytest
from cryptography.fernet import Fernet
from dishka import Provider, Scope
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from pydantic import SecretStr

import factories
from ada.adapters.db.workspace_repositories import SqlSourceLocks
from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemorySourceLocks,
    MemoryStore,
)
from ada.adapters.memory.web import MemoryWebBudget
from ada.adapters.secrets.fernet import FernetSecretBox
from ada.adapters.sources.examples import (
    EXAMPLES,
    NORDCAN_LUNG_SURVIVAL,
    SOTKANET_BREAST_SCREENING,
    STATFIN_CANCER_DEATHS,
    ExampleSource,
)
from ada.adapters.sources.files import LocalFileStore
from ada.adapters.sources.http import (
    USER_AGENT,
    HttpSourceReaders,
    SourceUnavailable,
    create_client,
)
from ada.adapters.sources.web import WebPageReader
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import ActorKind
from ada.core.models.analysis import FetchedData, Query
from ada.core.models.base import Id
from ada.core.models.errors import Conflict, Invalid, NotFound, Unavailable
from ada.core.models.events import EventType
from ada.core.models.operators import OperatorKind, operator_identity
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FoundBy,
    FreshnessKind,
    FreshnessPolicy,
    Provenance,
)
from ada.core.models.time import TimeRange
from ada.core.ports.analysis import AnalysisStore
from ada.core.ports.sources import SourceReaders
from ada.core.ports.web import WebExplorer
from ada.core.services.agents.research import ResearchReaders
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.refreshes import RefreshStatus, SnapshotSummary
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources, source_operator_id
from ada.core.services.sources.shaping import shape
from ada.core.services.sources.waiting import WaitingRefreshes
from api_support import FakeWeb, dispatcher, new_project, send, serve
from conftest import settings_in
from db_helpers import Repos, engine_for, unit_of_work
from fakes import (
    RECORDINGS,
    FakeAnalysisStore,
    FakeExplorer,
    FakeSourceReader,
    FakeSourceReaders,
    FixedClock,
    Replay,
    context_signature,
)
from memory import MemoryBackground, MemoryRepositories

pytestmark = pytest.mark.anyio

CSV = b"region,value\nHelsinki,74.3\n"
PUBLIC_URL = "https://ada.example"
KEY = Fernet.generate_key().decode()


@dataclass
class World:
    service: DataSources
    memory: MemoryStore
    reader: FakeSourceReader
    store: FakeAnalysisStore
    events: MemoryEventBus
    clock: FixedClock
    project_id: Id

    async def register(self, **changes: Any) -> DataSource:
        arguments: dict[str, Any] = {
            "name": "Screening",
            "access_kind": AccessKind.URL,
            "address": "https://example.test/data.csv",
            "format": DataFormat.CSV,
        }
        return await self.service.register(self.project_id, **(arguments | changes))

    def snapshots(self, source: DataSource) -> list[Any]:
        operator_id = source_operator_id(source)
        return [s for s in self.memory.snapshots.values() if s.operator_id == operator_id]

    def current(self, source: DataSource) -> list[Any]:
        return [s for s in self.snapshots(source) if s.superseded_at is None]


def data_sources(
    memory: MemoryStore,
    readers: SourceReaders,
    store: AnalysisStore,
    clock: FixedClock,
    explorer: WebExplorer | None = None,
) -> tuple[DataSources, MemoryEventBus]:
    events = MemoryEventBus()
    service = DataSources(
        projects=MemoryProjectRepository(memory),
        sources=MemoryDataSourceRepository(memory),
        operators=MemoryOperatorRepository(memory),
        snapshots=MemorySnapshotRepository(memory),
        readers=readers,
        checks=MemorySourceCheckLog(memory),
        store=store,
        events=events,
        clock=clock,
        locks=MemorySourceLocks(),
        explorer=explorer or FakeExplorer(),
        secrets=FernetSecretBox(KEY),
        public_url=PUBLIC_URL,
    )
    return service, events


@pytest.fixture
async def world() -> World:
    memory = MemoryStore()
    clock = FixedClock()
    reader = FakeSourceReader(CSV)
    reader.clock = clock
    store = FakeAnalysisStore()
    project = factories.project()
    memory.projects[project.id] = project
    readers = FakeSourceReaders({AccessKind.URL: reader, AccessKind.REQUEST: reader})
    service, events = data_sources(memory, readers, store, clock)
    return World(service, memory, reader, store, events, clock, project.id)


def probing(ttl_seconds: int = 60) -> FreshnessPolicy:
    return FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=ttl_seconds)


# Registering and editing


async def test_register_stores_the_source_and_its_source_operator(world: World) -> None:
    source = await world.register(declared_schema=factories.SCHEMA, options={"rows": "data"})

    assert await world.service.get(source.id) == source
    assert (source.revision, source.created_at) == (1, world.clock.at)
    operator = world.memory.operators[source_operator_id(source)]
    assert operator.id == operator_identity(
        world.project_id, OperatorKind.SOURCE, {"data_source_id": str(source.id)}, ()
    )
    assert (operator.inputs, operator.output, operator.materializing) == (
        (),
        factories.SCHEMA,
        True,
    )
    assert operator.created_by.kind is ActorKind.SYSTEM
    assert await world.service.list(world.project_id) == [source]


@pytest.mark.parametrize(
    "changes",
    [
        {"access_kind": AccessKind.BROWSER},
        {"freshness": FreshnessPolicy(kind=FreshnessKind.TTL)},
    ],
)
async def test_register_refuses_what_cannot_work(world: World, changes: dict[str, Any]) -> None:
    with pytest.raises(Invalid):
        await world.register(**changes)

    assert world.memory.data_sources == {}
    assert world.memory.operators == {}


async def test_an_update_changes_only_the_given_fields_from_the_current_revision(
    world: World,
) -> None:
    source = await world.register()
    policy = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=60)

    updated = await world.service.update(source.id, 1, name="Renamed", freshness=policy)

    assert (updated.name, updated.freshness, updated.revision) == ("Renamed", policy, 2)
    assert (updated.address, updated.options) == (source.address, source.options)
    with pytest.raises(Conflict):
        await world.service.update(source.id, 1, name="Second")
    assert (await world.service.get(source.id)).name == "Renamed"


# Web extract sources and provenance


PAGE = "https://example.test/page"
WEEK = 7 * 24 * 60 * 60


@pytest.fixture
def explorer() -> FakeExplorer:
    return FakeExplorer(rows=[{"county": "Uusimaa", "rate": "74.3"}, {"county": "Lappi"}])


@pytest.fixture
async def pages(world: World, explorer: FakeExplorer) -> World:
    """The world with web sources, read by the web reader on the fake Context.dev."""
    reader = WebPageReader(explorer, MemoryWebBudget(), world.clock, 300)
    readers = FakeSourceReaders({AccessKind.WEB: reader, AccessKind.URL: world.reader})
    world.service, world.events = data_sources(
        world.memory, readers, world.store, world.clock, explorer
    )
    return world


def extract_source(**changes: Any) -> dict[str, Any]:
    columns = (
        Column(name="county", type=ColumnType.TEXT),
        Column(name="rate", type=ColumnType.NUMBER),
    )
    return {
        "access_kind": AccessKind.WEB,
        "address": PAGE,
        "format": DataFormat.HTML,
        "options": {"operation": "extract", "instruction": "the rate per county"},
        "declared_schema": Schema(columns=columns),
    } | changes


async def test_an_extract_source_holds_the_rows_a_model_reads_off_the_page(
    pages: World, explorer: FakeExplorer
) -> None:
    source = await pages.register(**extract_source(provenance=Provenance(publisher="THL")))

    await pages.service.refresh(source.id)

    assert explorer.calls == [
        (
            "extract",
            {
                "url": PAGE,
                "instruction": "the rate per county",
                "columns": ["county", "rate"],
                "tags": ("ada", f"project:{pages.project_id}"),
            },
        )
    ]
    [written] = pages.store.written
    assert written.format is DataFormat.PARQUET
    assert [s.origin for s in pages.current(source)] == [PAGE]
    # The registration says the rows are model-extracted, whatever the agent passed.
    assert source.provenance == Provenance(publisher="THL", extracted_by_model=True)


async def test_an_extract_source_is_fresh_for_a_week_at_least_or_watched(pages: World) -> None:
    daily = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=WEEK // 7)
    with pytest.raises(Invalid, match="ttl of at least 7 days"):
        await pages.register(**extract_source(freshness=daily))
    with pytest.raises(Invalid, match="needs a declared schema"):
        await pages.register(**extract_source(declared_schema=None))
    with pytest.raises(Invalid, match="options.instruction"):
        await pages.register(**extract_source(options={"operation": "extract"}))

    weekly = await pages.register(
        **extract_source(freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=WEEK))
    )
    await pages.service.refresh(weekly.id, force=True)
    with pytest.raises(Invalid, match="fetched at most every 7 days"):
        await pages.service.refresh(weekly.id, force=True)
    # Watched, its monitor's deliveries refresh it however often the page changes.
    await pages.service.watch(weekly.id)
    await pages.service.refresh(weekly.id, force=True)


async def test_register_source_keeps_provenance(world: World) -> None:
    provenance = Provenance(
        publisher="THL",
        licence="unknown",
        found_by=FoundBy(query="stroke survival", scope="data"),
        note="no licence on the page",
    )

    source = await world.register(provenance=provenance)
    updated = await world.service.update(
        source.id,
        source.revision,
        provenance=provenance.model_copy(update={"licence": "CC BY 4.0"}),
    )

    assert source.provenance == provenance
    assert (await world.service.get(source.id)).provenance == updated.provenance
    assert updated.provenance is not None and updated.provenance.licence == "CC BY 4.0"
    assert (await world.register()).provenance is None


# Refreshing


async def test_the_first_refresh_writes_a_snapshot_and_announces_it(world: World) -> None:
    source = await world.register(declared_schema=factories.SCHEMA)

    result = await world.service.refresh(source.id)

    assert result.changed
    [snapshot] = world.snapshots(source)
    assert result.snapshot_ids == (snapshot.id,)
    [written] = world.store.written
    assert written.content == CSV
    # The reader gets an open time range: the whole source.
    [(_, time_range)] = world.reader.fetches
    assert time_range == TimeRange()
    assert (snapshot.parameters_key, snapshot.period, snapshot.superseded_at) == ("", None, None)
    assert snapshot.location == f"memory://{world.project_id}/{snapshot.content_hash}"
    stored = await world.service.get(source.id)
    assert (stored.last_checked_at, stored.last_error) == (world.clock.at, None)
    [event] = world.events.published
    assert event.type is EventType.SOURCE_REFRESHED
    assert event.payload == {"data_source_id": str(source.id), "changed": True}


async def test_an_edit_from_before_watching_keeps_the_monitor(world: World) -> None:
    source = await world.register()
    repository = MemoryDataSourceRepository(world.memory)

    await repository.set_monitor(source.id, "mon_1", "sealed", None)
    await repository.update(source.model_copy(update={"name": "Renamed"}), source.revision)

    stored = await repository.get(source.id)
    assert (stored.name, stored.monitor_id) == ("Renamed", "mon_1")
    assert await repository.monitor_secret_encrypted(source.id) == "sealed"


async def test_snapshot_keeps_origin(world: World) -> None:
    world.reader.origin = "https://final/url"
    source = await world.register()

    await world.service.refresh(source.id)

    assert [s.origin for s in world.snapshots(source)] == ["https://final/url"]


async def test_a_manual_source_is_fetched_only_when_asked_and_new_content_supersedes(
    world: World,
) -> None:
    source = await world.register()
    await world.service.refresh(source.id)
    [old] = world.snapshots(source)
    world.clock.advance(days=365)

    assert not (await world.service.refresh(source.id)).changed
    assert len(world.reader.fetches) == 1
    # A check that did not happen is not reported.
    assert len(world.events.published) == 1

    # The same content again adds no snapshot, but counts as a check.
    same = await world.service.refresh(source.id, force=True)
    assert (same.changed, same.snapshot_ids) == (False, ())
    assert (await world.service.get(source.id)).last_checked_at == world.clock.at

    world.reader.content = b"region,value\nHelsinki,80.1\n"
    forced = await world.service.refresh(source.id, force=True)

    assert forced.changed
    [current] = world.current(source)
    assert forced.snapshot_ids == (current.id,) != (old.id,)
    assert world.memory.snapshots[old.id].superseded_at == world.clock.at


async def test_a_ttl_source_is_fetched_again_a_lifetime_after_its_last_check(
    world: World,
) -> None:
    source = await world.register(
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    )
    await world.service.refresh(source.id)
    world.clock.advance(minutes=59)
    await world.service.refresh(source.id)
    assert len(world.reader.fetches) == 1

    world.clock.advance(minutes=1)
    await world.service.refresh(source.id)
    # Identical content wrote no snapshot, but the lifetime counts from this check.
    world.clock.advance(minutes=30)
    await world.service.refresh(source.id)

    assert len(world.reader.fetches) == 2


async def test_a_probe_fetches_only_when_its_token_changed(world: World) -> None:
    source = await world.register(freshness=probing())
    world.reader.token = "2026-06-12"
    await world.service.refresh(source.id)
    world.clock.advance(seconds=30)
    await world.service.refresh(source.id)
    # At most one probe per lifetime.
    assert len(world.reader.probes) == 1

    world.clock.advance(minutes=5)
    assert not (await world.service.refresh(source.id)).changed
    assert (len(world.reader.probes), len(world.reader.fetches)) == (2, 1)

    world.clock.advance(minutes=5)
    world.reader.token = "2026-11-01"
    world.reader.content = b"region,value\nHelsinki,80.1\n"
    assert (await world.service.refresh(source.id)).changed
    assert (await world.service.get(source.id)).last_probe_token == "2026-11-01"

    # A forced refresh does not probe.
    await world.service.refresh(source.id, force=True)
    assert (len(world.reader.probes), len(world.reader.fetches)) == (3, 3)


async def test_a_failed_fetch_keeps_the_old_snapshot_and_token_and_records_the_error(
    world: World,
) -> None:
    source = await world.register(freshness=probing())
    world.reader.token = "old"
    await world.service.refresh(source.id)
    [old] = world.snapshots(source)
    world.clock.advance(minutes=5)
    world.reader.token = "new"
    world.reader.content = RuntimeError("GET https://example.test/data.csv answered 503")

    with pytest.raises(RuntimeError):
        await world.service.refresh(source.id)

    assert world.current(source) == [old]
    stored = await world.service.get(source.id)
    assert stored.last_error == "GET https://example.test/data.csv answered 503"
    # Keeping the new token would make the next probe match: the new data never fetched.
    assert stored.last_probe_token == "old"
    assert world.events.published[-1].type is EventType.SOURCE_REFRESH_FAILED

    world.reader.content = b"region,value\nHelsinki,80.1\n"
    await world.service.refresh(source.id, force=True)
    assert (await world.service.get(source.id)).last_error is None


async def test_a_refresh_waited_for_says_how_it_went_instead_of_raising(world: World) -> None:
    refreshes = WaitingRefreshes(world.service, MemorySnapshotRepository(world.memory))
    source = await world.register()

    fetched = await refreshes.refresh_now(source.id)
    unchanged = await refreshes.refresh_now(source.id, force=True)
    world.reader.content = RuntimeError("GET https://example.test/data.csv answered 503")
    failed = await refreshes.refresh_now(source.id, force=True)

    [snapshot] = world.snapshots(source)
    summary = SnapshotSummary(
        id=snapshot.id, row_count=snapshot.row_count, fetched_at=snapshot.fetched_at
    )
    assert (fetched.status, fetched.snapshot, fetched.error) == (
        RefreshStatus.FETCHED,
        summary,
        None,
    )
    assert (unchanged.status, unchanged.snapshot) == (RefreshStatus.UNCHANGED, summary)
    # The last good snapshot stays current; the failure is recorded as for the worker.
    assert (failed.status, failed.snapshot, failed.error) == (
        RefreshStatus.FAILED,
        summary,
        "GET https://example.test/data.csv answered 503",
    )
    assert (await world.service.get(source.id)).last_error == failed.error

    async def hanging(*arguments: Any) -> None:
        await asyncio.sleep(30)

    with patch.object(world.reader, "fetch", hanging):
        slow = await refreshes.refresh_now(source.id, force=True, timeout_seconds=1)
    assert slow.status is RefreshStatus.FAILED
    assert slow.error is not None and "longer than 1 s" in slow.error
    with pytest.raises(Invalid):
        await refreshes.refresh_now(source.id, timeout_seconds=61)


async def test_content_that_does_not_fit_the_options_fails_the_refresh(world: World) -> None:
    world.reader.content = b'{"other": []}'
    world.reader.format = DataFormat.JSON
    source = await world.register(format=DataFormat.JSON, options={"rows": "data"})

    with pytest.raises(Invalid):
        await world.service.refresh(source.id)

    assert world.store.written == []
    assert (await world.service.get(source.id)).last_error is not None
    with pytest.raises(NotFound):
        await world.service.refresh(factories.project().id)


async def test_due_lists_the_sources_whose_policy_says_now(world: World) -> None:
    hourly = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=3600)
    manual = await world.register(name="Manual")
    ttl = await world.register(name="TTL", freshness=hourly)
    probe = await world.register(name="Probe", freshness=probing(86400))
    push = await world.register(name="Push", freshness=FreshnessPolicy(kind=FreshnessKind.PUSH))

    # Never refreshed: the scheduled policies are due, the others wait to be asked.
    assert [s.id for s in await world.service.due()] == [ttl.id, probe.id]

    for source in (manual, ttl, probe, push):
        await world.service.refresh(source.id)
    assert await world.service.due() == []

    world.clock.advance(hours=1)
    world.reader.content = RuntimeError("down")
    with pytest.raises(RuntimeError):
        await world.service.refresh(ttl.id)
    # A failed source waits a lifetime too.
    assert await world.service.due() == []

    world.clock.advance(days=1)
    assert [s.id for s in await world.service.due()] == [ttl.id, probe.id]


# Through the container and PostgreSQL


async def test_a_failed_refresh_stays_recorded_when_the_caller_rolls_back(
    migrated_database_url: str, tmp_path: Path
) -> None:
    reader = FakeSourceReader()
    reader.content = Unavailable("GET https://example.test/data.csv answered 503")
    readers = Provider(scope=Scope.APP)
    readers.provide(lambda: FakeSourceReaders({AccessKind.URL: reader}), provides=SourceReaders)
    settings = settings_in(tmp_path, migrated_database_url)
    container = create_container(settings, MemoryBackground(), readers)
    try:
        async with container() as request:
            project = await (await request.get(ProjectService)).create("P")
            source = await (await request.get(SourceService)).register(
                project.id, "S", AccessKind.URL, "https://example.test/data.csv", DataFormat.CSV
            )
        with pytest.raises(Unavailable):
            async with container() as request:
                await (await request.get(SourceService)).refresh(source.id, force=True)
        async with container() as request:
            after = await (await request.get(SourceService)).get(source.id)
    finally:
        await container.close()

    assert after.last_error == "GET https://example.test/data.csv answered 503"
    assert after.last_checked_at is not None
    # The record does not count as an edit.
    assert after.revision == source.revision


async def test_the_container_shares_the_readers_and_closes_them(
    unreachable_settings: Settings,
) -> None:
    container = create_container(unreachable_settings, FastapiProvider(), MemoryRepositories())
    try:
        readers = await container.get(SourceReaders)
        # Wrapped, so a research turn counts its paid reads.
        assert isinstance(readers, ResearchReaders)
        assert isinstance(readers.readers, HttpSourceReaders)
        async with container() as request:
            service = await request.get(SourceService)
            assert isinstance(service, DataSources)
            # The readers, and with them the HTTP client, are shared by every request.
            assert service.readers is readers
    finally:
        await container.close()
    assert readers.readers.readers[AccessKind.URL].client.is_closed


# The HTTP readers


class Server:
    """Answers with `handler` and keeps every request it saw."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def reader(self, kind: AccessKind = AccessKind.URL, **settings: Any):  # noqa: ANN201
        client = create_client(httpx.MockTransport(self))
        settings = {"allow_private": True} | settings
        return HttpSourceReaders(client, FixedClock(), **settings).for_kind(kind)


def source(kind: AccessKind = AccessKind.URL, **changes: Any) -> DataSource:
    return factories.data_source(factories.project().id, access_kind=kind, **changes)


async def test_a_url_source_is_fetched_with_get_and_its_params_and_headers() -> None:
    server = Server(lambda request: httpx.Response(200, content=b"a,b\n1,2\n"))
    options = {
        "params": {"genders": "total", "years": [2023, 2024]},
        "headers": {"X-Key": "k"},
        # A URL source ignores a method and a body.
        "method": "POST",
        "body": {"q": 1},
    }

    fetched = await server.reader().fetch(
        source(address="https://x.test/data?indicator=3621", options=options), TimeRange()
    )

    assert (fetched.content, fetched.format) == (b"a,b\n1,2\n", DataFormat.CSV)
    assert fetched.fetched_at == FixedClock().now()
    [request] = server.requests
    assert (request.method, request.content) == ("GET", b"")
    assert str(request.url) == (
        "https://x.test/data?indicator=3621&genders=total&years=2023&years=2024"
    )
    assert request.headers["x-key"] == "k"
    assert request.headers["user-agent"] == USER_AGENT


async def test_a_request_source_sends_its_method_headers_and_body() -> None:
    server = Server(lambda request: httpx.Response(200, content=b"a\n1\n"))
    options = {"body": {"query": []}, "headers": {"Accept": "text/csv"}}

    await server.reader(AccessKind.REQUEST).fetch(
        source(AccessKind.REQUEST, options=options), TimeRange()
    )
    await server.reader(AccessKind.REQUEST).fetch(
        source(AccessKind.REQUEST, options={"method": "PUT", "body": "q=1"}), TimeRange()
    )

    posted, put = server.requests
    assert (posted.method, json.loads(posted.content)) == ("POST", {"query": []})
    assert posted.headers["accept"] == "text/csv"
    assert (put.method, put.content) == ("PUT", b"q=1")


async def test_an_error_answer_or_no_answer_makes_the_source_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SourceUnavailable, match="GET https://example.test/data.csv answered 503"):
        await Server(lambda request: httpx.Response(503)).reader().fetch(source(), TimeRange())
    with pytest.raises(SourceUnavailable, match="connection refused"):
        await Server(refuse).reader().fetch(source(), TimeRange())
    with pytest.raises(Invalid):
        await Server(refuse).reader().fetch(source(address="ftp://x.test/a.csv"), TimeRange())


async def test_only_public_addresses_are_read_redirects_included() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"Location": "https://93.184.215.14/data.csv"})
        if request.url.path == "/metadata":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})
        return httpx.Response(200, content=b"a\n1\n")

    server = Server(handler)
    public = server.reader(allow_private=False)

    fetched = await public.fetch(source(address="https://93.184.216.34/moved"), TimeRange())
    with pytest.raises(Invalid, match="localhost is not a public address"):
        await public.fetch(source(address="http://localhost:8000/admin"), TimeRange())
    with pytest.raises(Invalid, match="169.254.169.254"):
        await public.fetch(source(address="https://93.184.216.34/metadata"), TimeRange())
    # A document at an address is downloaded by the URL reader, under the same rule.
    with pytest.raises(Invalid, match="localhost is not a public address"):
        await server.reader(AccessKind.DOCUMENT, allow_private=False).fetch(
            source(AccessKind.DOCUMENT, address="http://localhost/a.pdf"), TimeRange()
        )
    allowed = await server.reader().fetch(source(address="http://127.0.0.1/a"), TimeRange())

    assert (fetched.content, fetched.origin) == (b"a\n1\n", "https://93.184.215.14/data.csv")
    assert allowed.content == b"a\n1\n"
    assert [r.url.host for r in server.requests] == [
        "93.184.216.34",
        "93.184.215.14",
        "93.184.216.34",
        "127.0.0.1",
    ]


async def test_the_address_connected_to_is_the_one_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\na\n1\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    resolve = socket.getaddrinfo
    answers = iter(["93.184.216.34"])

    def rebinding(host: str | bytes, *args: Any, **kwargs: Any) -> Any:
        # Public when the reader checks the name, this machine when it is connected to.
        if host not in ("rebind.test", b"rebind.test"):
            return resolve(host, *args, **kwargs)
        ip = next(answers, "127.0.0.1")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    # A proxy from the environment keeps working; this test then connects directly.
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    async with create_client() as client:
        assert client._mounts
    monkeypatch.setenv("NO_PROXY", "*")
    rebound = source(address=f"http://rebind.test:{port}/data.csv")
    async with server:
        async with create_client() as client:
            public = HttpSourceReaders(client, FixedClock()).for_kind(AccessKind.URL)
            with pytest.raises(Invalid, match=r"rebind.test is not a public address \(127"):
                await public.fetch(rebound, TimeRange())
        async with create_client(allow_private=True) as client:
            private = HttpSourceReaders(client, FixedClock(), allow_private=True)
            fetched = await private.for_kind(AccessKind.URL).fetch(rebound, TimeRange())

    assert fetched.content == b"a\n1\n"


async def test_an_answer_over_the_size_limit_is_refused() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"x" * 40

    declared = Server(lambda request: httpx.Response(200, content=b"x" * 101))
    streamed = Server(lambda request: httpx.Response(200, content=chunks()))

    for server in (declared, streamed):
        with pytest.raises(SourceUnavailable, match="more than 100 bytes"):
            await server.reader(max_bytes=100).fetch(source(), TimeRange())
    # The probe's HEAD request has no body, whatever length GET's would have.
    tagged = Server(lambda r: httpx.Response(200, headers={"ETag": "v", "Content-Length": "101"}))
    assert await tagged.reader(max_bytes=100).probe(source()) == "etag:v"


async def test_an_encoded_answer_is_decoded_within_the_size_limit() -> None:
    layered = gzip.compress(zlib.compress(b"a\n1\n"))
    # About 200 bytes that hold 20 MB of zeros.
    bomb = gzip.compress(gzip.compress(bytes(20_000_000)))

    def encoded(content: bytes, encoding: str) -> Server:
        headers = {"Content-Encoding": encoding}
        # A stream, as from the network: httpx decodes `content` when it is given.
        stream = httpx.ByteStream(content)
        return Server(lambda request: httpx.Response(200, headers=headers, stream=stream))

    fetched = await encoded(layered, "deflate, gzip").reader().fetch(source(), TimeRange())
    tracemalloc.start()
    try:
        with pytest.raises(SourceUnavailable, match="more than 100,000 bytes"):
            await encoded(bomb, "gzip, gzip").reader(max_bytes=100_000).fetch(source(), TimeRange())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert fetched.content == b"a\n1\n"
    # Refused while decoding, not after the 20 MB are in memory.
    assert peak < 2_000_000


async def test_the_probe_reads_a_declared_field_or_hashes_the_answer() -> None:
    answers = iter([{"meta": {"updated": 5}}, {"id": 1}, {"v": 1}, {"v": 1}, {"v": 2}])
    server = Server(lambda request: httpx.Response(200, json=next(answers)))
    field = source(options={"probe": {"url": "https://x.test/m", "field": "meta.updated"}})
    hashed = source(options={"probe": {"url": "https://x.test/m"}})

    assert await server.reader().probe(field) == "5"
    with pytest.raises(Invalid, match="meta.updated"):
        await server.reader().probe(field)
    tokens = [await server.reader().probe(hashed) for _ in range(3)]

    assert tokens[0] == tokens[1] != tokens[2]
    assert tokens[0].startswith("sha256:")
    assert {(r.method, str(r.url)) for r in server.requests} == {("GET", "https://x.test/m")}


@pytest.mark.parametrize(
    ("status", "headers", "token"),
    [
        (200, {"ETag": '"abc"', "Last-Modified": "Fri, 13 Nov 2026 10:00:00 GMT"}, 'etag:"abc"'),
        (
            200,
            {"Last-Modified": "Fri, 13 Nov 2026 10:00:00 GMT"},
            "last-modified:Fri, 13 Nov 2026 10:00:00 GMT",
        ),
        (405, {}, None),
    ],
)
async def test_without_a_declared_probe_the_http_validator_is_the_token(
    status: int, headers: dict[str, str], token: str | None
) -> None:
    server = Server(lambda request: httpx.Response(status, headers=headers))

    assert await server.reader().probe(source()) == token
    [request] = server.requests
    assert request.method == "HEAD"


# Shaping


def fetched(content: bytes, format: DataFormat = DataFormat.JSON) -> FetchedData:
    return FetchedData(
        content=content, format=format, fetched_at=factories.NOW, origin="https://x.test"
    )


def shaped_json(document: Any, **options: Any) -> list[dict[str, Any]]:
    return json.loads(shape(fetched(json.dumps(document).encode()), options).content)


def test_json_is_flattened_into_rows_with_every_column() -> None:
    document = {"result": [{"label": "Finland", "survival": {"value": "17.9"}}, {"extra": 1}]}

    assert shaped_json(document, rows="result") == [
        {"label": "Finland", "survival_value": "17.9", "extra": None},
        {"label": None, "survival_value": None, "extra": 1},
    ]
    fields = {
        "country": "label",
        "survival": {"path": "survival.value", "type": "number"},
        "missing": "survival.lowCI",
    }
    assert shaped_json(document, rows="result", fields=fields)[0] == {
        "country": "Finland",
        "survival": 17.9,
        "missing": None,
    }


def test_csv_is_rewritten_as_utf8_with_commas() -> None:
    content = "﻿Title\nregion;value\r\nÅland;..\r\nHelsinki;74,3\r\n".encode()
    options = {"csv": {"delimiter": ";", "null_values": [".."], "skip_rows": 1}}

    assert shape(fetched(content, DataFormat.CSV), options).content.decode() == (
        'region,value\nÅland,\nHelsinki,"74,3"\n'
    )
    # Without options a CSV is kept as it came.
    plain = fetched(b"a;b\r\n1;2\r\n", DataFormat.CSV)
    assert shape(plain, {}) == plain


@pytest.mark.parametrize(
    ("content", "format", "options"),
    [
        (b'{"data": []}', DataFormat.JSON, {"rows": "dataset"}),
        (b'[{"v": "n/a"}]', DataFormat.JSON, {"fields": {"v": {"path": "v", "type": "number"}}}),
    ],
)
def test_an_answer_of_another_shape_is_invalid(
    content: bytes, format: DataFormat, options: dict[str, Any]
) -> None:
    with pytest.raises(Invalid):
        shape(fetched(content, format), options)


# Documents


def pdf(*pages: str) -> bytes:
    """A minimal valid PDF whose pages draw the given content streams in Helvetica."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for stream in pages:
        objects.append(f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream")
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def text(x: int, y: int, words: str) -> str:
    return f"BT /F1 10 Tf {x} {y} Td ({words}) Tj ET"


# Two pages: text only, then a heading over a ruled two-by-two table.
STRATEGY_PDF = pdf(
    "\n".join([text(20, 170, "Cancer strategy"), text(20, 150, "Equal care for all")]),
    "\n".join(
        [
            text(20, 170, "Incidence"),
            "0.5 w 20 40 m 220 40 l S 20 70 m 220 70 l S 20 100 m 220 100 l S",
            "20 40 m 20 100 l S 120 40 m 120 100 l S 220 40 m 220 100 l S",
            text(25, 80, "region"),
            text(125, 80, "cases"),
            text(25, 50, "Uusimaa"),
            text(125, 50, "13,300"),
        ]
    ),
)


class Documents:
    """Document sources read through the real readers and store, from a server that
    answers with `answer`."""

    def __init__(self, data_dir: Path) -> None:
        memory = MemoryStore()
        project = factories.project()
        memory.projects[project.id] = project
        self.project_id = project.id
        self.answer = STRATEGY_PDF
        # What Context.dev's parse API answers: the status and the JSON body.
        self.parsed: tuple[int, dict[str, Any]] = (200, {"success": True, "markdown": MARKDOWN})
        self.server = Server(self._answer)
        self.store = DuckDbAnalysisStore(data_dir)
        self.files = LocalFileStore(data_dir)
        readers = HttpSourceReaders(
            create_client(httpx.MockTransport(self.server)),
            FixedClock(),
            self.files,
            "ctxt_test",
            allow_private=True,
        )
        self.service, _ = data_sources(memory, readers, self.store, FixedClock())

    def _answer(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.context.dev":
            status, body = self.parsed
            return httpx.Response(status, json=body)
        return httpx.Response(200, content=self.answer)

    async def register(self, **changes: Any) -> DataSource:
        arguments: dict[str, Any] = {
            "name": "Strategy",
            "access_kind": AccessKind.DOCUMENT,
            "address": "https://example.test/strategy.pdf",
            "format": DataFormat.PDF,
        }
        return await self.service.register(self.project_id, **(arguments | changes))

    async def rows(self, source: DataSource) -> list[tuple[object, ...]]:
        assert (await self.service.refresh(source.id)).changed
        snapshot = await self.service.snapshots.current(source_operator_id(source), "")
        assert snapshot is not None
        query = Query(sql="SELECT * FROM s", relations={"s": snapshot.location})
        return list((await self.store.run(query, limit=100)).rows)


@pytest.fixture
def documents(tmp_path: Path) -> Documents:
    return Documents(tmp_path / "data")


async def test_a_document_source_has_the_columns_of_its_extract_mode(
    documents: Documents,
) -> None:
    pages = await documents.register()
    tables = await documents.register(options={"extract": "tables"})

    assert pages.declared_schema is not None and tables.declared_schema is not None
    assert [c.name for c in pages.declared_schema.columns] == ["page", "text"]
    assert [(c.name, c.type.value) for c in tables.declared_schema.columns] == [
        ("page", "integer"),
        ("table", "integer"),
        ("row", "integer"),
        ("cells", "json"),
    ]
    operator = await documents.service.operators.get(source_operator_id(tables))
    assert operator.output == tables.declared_schema
    # The columns are the mode's, so the mode cannot change on an edit.
    with pytest.raises(Invalid, match="register another source"):
        await documents.service.update(pages.id, 1, options={"extract": "tables"})
    for refused in [
        {"options": {"extract": "words"}},
        {"format": DataFormat.CSV},
        {"access_kind": AccessKind.URL},
        {"declared_schema": factories.SCHEMA},
    ]:
        with pytest.raises(Invalid):
            await documents.register(**refused)


async def test_a_pdf_is_fetched_and_extracted_as_pages_or_as_table_rows(
    documents: Documents,
) -> None:
    pages = await documents.rows(await documents.register())
    tables = await documents.rows(await documents.register(options={"extract": "tables"}))

    assert pages == [
        (1, "Cancer strategy\nEqual care for all"),
        (2, "Incidence\nregion cases\nUusimaa 13,300"),
    ]
    assert tables == [
        (2, 1, 1, ["region", "cases"]),
        (2, 1, 2, ["Uusimaa", "13,300"]),
    ]
    assert [r.method for r in documents.server.requests] == ["GET", "GET"]


MARKDOWN = """# Handout

<!-- page 1 -->
## Delays in access to care

<!-- page 2 -->
Time to treatment

| Step | Private | Public |
| --- | ---: | ---: |
| First contact | 42 | 43 |
| Specialist \\| visit | 147 | 204 |

Not a table any more.
"""


async def test_an_uploaded_pdf_is_parsed_by_context_dev_into_pages_or_table_rows(
    documents: Documents,
) -> None:
    stored = await documents.files.put(documents.project_id, STRATEGY_PDF, ".pdf")
    again = await documents.files.put(documents.project_id, STRATEGY_PDF, ".pdf")
    engine = {"engine": "context.dev"}

    pages = await documents.rows(await documents.register(address=stored.address, options=engine))
    tables = await documents.rows(
        await documents.register(address=stored.address, options=engine | {"extract": "tables"})
    )

    # Stored once per content; the file is read from the store, never fetched.
    assert again == stored and stored.address.startswith("upload://")
    assert pages == [
        (1, "## Delays in access to care"),
        (2, MARKDOWN.split("<!-- page 2 -->")[1].strip()),
    ]
    assert tables == [
        (2, 1, 1, ["Step", "Private", "Public"]),
        (2, 1, 2, ["First contact", "42", "43"]),
        (2, 1, 3, ["Specialist | visit", "147", "204"]),
    ]
    parse = [r for r in documents.server.requests if r.url.host == "api.context.dev"]
    assert [r.url.path for r in parse] == ["/v1/parse", "/v1/parse"]
    assert parse[0].headers["authorization"] == "Bearer ctxt_test"
    assert parse[0].content == STRATEGY_PDF
    # Context.dev's refusals are the source's readable last error: only the status and the
    # error code, since an authentication error may echo the key.
    documents.parsed = (402, {"error_code": "NO_CREDITS", "message": "key ctxt_test is out"})
    broke = await documents.register(
        address=stored.address, options=engine | {"extract": "tables"}, name="B"
    )
    with pytest.raises(Invalid, match=r"no credits left: NO_CREDITS \(HTTP 402\)$") as refused:
        await documents.service.refresh(broke.id)
    assert "ctxt_test" not in str(refused.value)
    with pytest.raises(Invalid, match="options.engine must be one of"):
        await documents.register(options={"engine": "magic"})


async def test_a_pdf_that_cannot_be_read_fails_the_refresh_readably(
    documents: Documents,
) -> None:
    source = await documents.register()

    for answer, reason in [
        (b"%PDF-1.4\nnot really", "is not a readable PDF"),
        (b"<html>Moved</html>", "is not a PDF: it starts with '<html>Moved</html>'"),
    ]:
        documents.answer = answer
        with pytest.raises(Invalid, match=reason):
            await documents.service.refresh(source.id)
        error = (await documents.service.get(source.id)).last_error
        assert error is not None
        assert error.startswith(f"https://example.test/strategy.pdf {reason}")


# The examples, against their recorded answers


@dataclass
class Recorded:
    service: DataSources
    store: FakeAnalysisStore
    replay: Replay
    clock: FixedClock
    project_id: Id


@pytest.fixture
def recorded() -> Recorded:
    memory = MemoryStore()
    clock = FixedClock()
    replay = Replay()
    project = factories.project()
    memory.projects[project.id] = project
    store = FakeAnalysisStore()
    readers = HttpSourceReaders(
        create_client(httpx.MockTransport(replay)), clock, allow_private=True
    )
    service, _ = data_sources(memory, readers, store, clock)
    return Recorded(service, store, replay, clock, project.id)


def test_every_recording_is_small() -> None:
    for path in RECORDINGS.iterdir():
        assert path.stat().st_size < 200_000, path.name


async def test_sotkanet_is_probed_fetched_and_not_fetched_again_while_unchanged(
    recorded: Recorded,
) -> None:
    service = recorded.service
    source = await service.register(recorded.project_id, **SOTKANET_BREAST_SCREENING.registration())

    assert (await service.refresh(source.id)).changed
    recorded.clock.advance(days=1)
    assert not (await service.refresh(source.id)).changed

    # The probe's token is the indicator's data-updated date, and it has not moved.
    assert [r.method + " " + r.url.path for r in recorded.replay.requests] == [
        "GET /rest/1.1/indicators/3621",
        "GET /rest/1.1/json",
        "GET /rest/1.1/indicators/3621",
    ]
    assert (await service.get(source.id)).last_probe_token == "2026-06-12"
    [written] = recorded.store.written
    rows = json.loads(written.content)
    assert len(rows) == 880
    assert rows[0] == {
        "indicator": 3621,
        "region": 52,
        "year": 2023,
        "gender": "total",
        "value": 86.6,
        "count": 560,
        # From the year, by the `period` option: the time role's columns.
        "period_start": "2023-01-01",
        "period_end": "2023-12-31",
    }


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.name.split(" (")[0])
async def test_each_example_declares_exactly_the_columns_it_produces(
    recorded: Recorded, example: ExampleSource
) -> None:
    source = await recorded.service.register(recorded.project_id, **example.registration())

    assert (await recorded.service.refresh(source.id)).changed

    [written] = recorded.store.written
    if written.format.value == "json":
        rows = json.loads(written.content)
        columns = list(rows[0])
    else:
        rows = list(csv.DictReader(io.StringIO(written.content.decode())))
        columns = list(rows[0])
    assert example.declared_schema is not None
    assert columns == [column.name for column in example.declared_schema.columns]
    if example is STATFIN_CANCER_DEATHS:
        # 26 areas, from the whole country to Åland, for four causes.
        assert len(rows) == 26 * 4
    if example is NORDCAN_LUNG_SURVIVAL:
        # The spec's Nordic comparison: Finland 17.9 (men) and 30.8 (women), 2020-2024.
        finland = {
            row["sex"]: row["survival"]
            for row in rows
            if row["country"] == "Finland" and row["period"] == "2020-2024"
        }
        assert finland == {1: 17.9, 2: 30.8}


# Watched sources


def web_page(**changes: Any) -> dict[str, Any]:
    return {"access_kind": AccessKind.WEB, "address": PAGE, "format": DataFormat.HTML} | changes


async def test_watch_stores_encrypted_secret_and_sets_push(
    pages: World, explorer: FakeExplorer
) -> None:
    source = await pages.register(**web_page())

    watched = await pages.service.watch(source.id)

    sealed = pages.memory.monitor_secrets[source.id]
    assert sealed != "test-secret"
    assert FernetSecretBox(KEY).decrypt(sealed) == "test-secret"
    assert (watched.monitor_id, watched.freshness.kind) == ("mon_1", FreshnessKind.PUSH)
    assert "test-secret" not in watched.model_dump_json()
    webhook = f"{PUBLIC_URL}/api/hooks/context/{source.id}"
    assert explorer.calls == [("watch", {"url": PAGE, "webhook_url": webhook})]
    elsewhere = await pages.register(address="ftp://example.test/data.csv")
    with pytest.raises(Invalid, match="http"):
        await pages.service.watch(elsewhere.id)


async def test_watching_again_replaces_the_monitor_and_unwatch_restores_the_policy(
    pages: World, explorer: FakeExplorer
) -> None:
    weekly = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=WEEK)
    source = await pages.register(**web_page(freshness=weekly))
    await pages.service.watch(source.id)

    await pages.service.watch(source.id)
    unwatched = await pages.service.unwatch(source.id)

    assert [call[0] for call in explorer.calls] == ["watch", "watch", "unwatch", "unwatch"]
    assert explorer.calls[2] == ("unwatch", {"monitor_id": "mon_1"})
    assert (unwatched.monitor_id, unwatched.freshness) == (None, weekly)
    assert source.id not in pages.memory.monitor_secrets


async def test_a_watched_address_cannot_change(pages: World) -> None:
    source = await pages.register(**web_page())
    watched = await pages.service.watch(source.id)

    renamed = await pages.service.update(
        source.id, watched.revision, name="Renamed", address=f" {source.address} "
    )
    with pytest.raises(Invalid, match="Stop watching it before changing the address"):
        await pages.service.update(source.id, renamed.revision, address="https://x.test/b")
    unwatched = await pages.service.unwatch(source.id)
    moved = await pages.service.update(source.id, unwatched.revision, address="https://x.test/b")

    assert moved.address == "https://x.test/b"


async def test_a_failed_replacement_keeps_the_old_monitor(
    pages: World, explorer: FakeExplorer
) -> None:
    source = await pages.register(**web_page())
    before = await pages.service.watch(source.id)
    sealed = pages.memory.monitor_secrets[source.id]
    explorer.calls.clear()
    explorer.failure = Unavailable("the monitor service is down")

    with pytest.raises(Unavailable):
        await pages.service.watch(source.id)

    assert await pages.service.get(source.id) == before
    assert pages.memory.monitor_secrets[source.id] == sealed
    assert [call[0] for call in explorer.calls] == ["watch"]


async def test_watch_without_public_url_fails_clearly(pages: World, explorer: FakeExplorer) -> None:
    source = await pages.register(**web_page())
    pages.service.public_url = None

    with pytest.raises(Invalid, match="watching is not configured: ADA_PUBLIC_URL is not set"):
        await pages.service.watch(source.id)
    assert explorer.calls == []


@pytest.fixture
def watched(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    settings = settings_in(tmp_path).model_copy(
        update={"ada_public_url": PUBLIC_URL, "secret_key": SecretStr(KEY)}
    )
    with serve(settings, FakeWeb()) as client:
        project = new_project(client)
        body = {"name": "Page", "access_kind": "web", "format": "html", "address": PAGE}
        source = send(client, "POST", f"/projects/{project['id']}/sources", body, 201)
        send(client, "POST", f"/sources/{source['id']}/watch")
        yield client, source["id"]


def deliver(
    client: TestClient, source_id: Any, secret: str = "test-secret", at: float | None = None
) -> Any:
    body = b'{"event": "change.detected"}'
    signature = context_signature(secret, body, int(time.time() if at is None else at))
    return client.post(
        f"/api/hooks/context/{source_id}", content=body, headers={"x-context-signature": signature}
    )


def test_hook_good_signature_queues_forced_refresh(watched: tuple[TestClient, str]) -> None:
    client, source_id = watched

    response = deliver(client, source_id)

    assert (response.status_code, response.json()) == (202, {"status": "queued"})
    assert [(str(i), force) for i, force in dispatcher(client).refreshes] == [(source_id, True)]
    assert "test-secret" not in response.text


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "t=1",
        "t=x,v1=00",
        "garbage",
        f"t={9 * 10**399},v1=00",
        "t=" + "9" * 5000 + ",v1=00",
    ],
)
def test_hook_rejects_bad_signature(watched: tuple[TestClient, str], header: str | None) -> None:
    client, source_id = watched
    headers = {} if header is None else {"x-context-signature": header}

    malformed = client.post(f"/api/hooks/context/{source_id}", content=b"{}", headers=headers)
    wrong = deliver(client, source_id, secret="another-secret")

    assert (malformed.status_code, wrong.status_code) == (401, 401)
    assert dispatcher(client).refreshes == []


def test_hook_rejects_stale_timestamp(watched: tuple[TestClient, str]) -> None:
    client, source_id = watched

    old = deliver(client, source_id, at=time.time() - 301)
    future = deliver(client, source_id, at=time.time() + 301)

    assert (old.status_code, future.status_code) == (401, 401)
    assert dispatcher(client).refreshes == []


def test_hook_unknown_source_is_404(watched: tuple[TestClient, str]) -> None:
    client, source_id = watched
    send(client, "DELETE", f"/sources/{source_id}/watch")

    unwatched = deliver(client, source_id)
    unknown = deliver(client, uuid7())

    assert (unwatched.status_code, unknown.status_code) == (404, 404)
    assert dispatcher(client).refreshes == []


def postgres_sources(explorer: FakeExplorer) -> Callable[[Repos], DataSources]:
    def service(repos: Repos) -> DataSources:
        session = repos.data_sources.session  # type: ignore[attr-defined]
        readers = FakeSourceReaders({AccessKind.WEB: FakeSourceReader()})
        return DataSources(
            repos.projects,
            repos.data_sources,
            repos.operators,
            repos.snapshots,
            readers,
            MemorySourceCheckLog(MemoryStore()),
            FakeAnalysisStore(),
            MemoryEventBus(),
            FixedClock(),
            SqlSourceLocks(session),
            explorer,
            FernetSecretBox(KEY),
            PUBLIC_URL,
        )

    return service


async def test_watch_is_stored_encrypted_in_postgres(migrated_database_url: str) -> None:
    explorer = FakeExplorer()
    secrets = FernetSecretBox(KEY)
    service = postgres_sources(explorer)

    async with engine_for(migrated_database_url) as engine:
        async with unit_of_work(engine) as repos:
            project = factories.project()
            await repos.projects.add(project)
            source = await service(repos).register(
                project.id, "Page", AccessKind.WEB, PAGE, DataFormat.HTML
            )
            watched = await service(repos).watch(source.id)
        async with unit_of_work(engine) as repos:
            column = await repos.data_sources.monitor_secret_encrypted(source.id)
            verified = await service(repos).verify_push(
                source.id,
                b"{}",
                context_signature("test-secret", b"{}", int(time.time())),
                datetime.now(UTC),
            )

    assert column is not None and column != "test-secret"
    assert secrets.decrypt(column) == "test-secret"
    assert verified
    assert (watched.monitor_id, watched.freshness.kind) == ("mon_1", FreshnessKind.PUSH)
    assert "test-secret" not in watched.model_dump_json()


async def test_a_policy_edit_waits_for_unwatch_in_postgres(migrated_database_url: str) -> None:
    explorer = FakeExplorer()
    service = postgres_sources(explorer)
    weekly = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=WEEK)
    deleting, deleted = asyncio.Event(), asyncio.Event()

    async def unwatch(monitor_id: str) -> None:
        deleting.set()
        await deleted.wait()

    async with engine_for(migrated_database_url) as engine:
        async with unit_of_work(engine) as repos:
            project = factories.project()
            await repos.projects.add(project)
            source = await service(repos).register(
                project.id, "Page", AccessKind.WEB, PAGE, DataFormat.HTML, freshness=weekly
            )
            watched = await service(repos).watch(source.id)
        explorer.unwatch = unwatch  # type: ignore[method-assign]

        async def unwatch_source() -> DataSource:
            async with unit_of_work(engine) as repos:
                return await service(repos).unwatch(source.id)

        async def edit() -> DataSource:
            async with unit_of_work(engine) as repos:
                daily = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=86_400)
                return await service(repos).update(source.id, watched.revision, freshness=daily)

        unwatching = asyncio.create_task(unwatch_source())
        await deleting.wait()
        editing = asyncio.create_task(edit())
        done, _ = await asyncio.wait({editing}, timeout=0.3)
        deleted.set()
        unwatched = await unwatching
        # It waited for unwatch, then found the source changed instead of being undone.
        with pytest.raises(Conflict):
            await editing

    assert not done
    assert unwatched.freshness == weekly


async def test_token_pagination_keeps_params_and_joins_before_shaping() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("pageToken", "1"))
        return httpx.Response(
            200,
            json={
                "data": {"items": [{"id": page}]},
                **({"nextPageToken": str(page + 1)} if page < 3 else {}),
            },
        )

    server = Server(answer)
    options = {
        "rows": "data.items",
        "params": {"country": "FI"},
        "paginate": {"token": "nextPageToken", "param": "pageToken", "delay_seconds": 0},
    }
    fetched = await server.reader().fetch(
        source(address="https://x.test/search?size=100", format=DataFormat.JSON, options=options),
        TimeRange(),
    )
    assert json.loads(shape(fetched, options).content) == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert dict(server.requests[1].url.params) == {"size": "100", "country": "FI", "pageToken": "2"}
    assert fetched.origin == str(server.requests[0].url)
    with pytest.raises(SourceUnavailable, match="bytes"):
        await server.reader(max_bytes=len(fetched.content)).fetch(
            source(format=DataFormat.JSON, options=options), TimeRange()
        )


async def test_page_pagination_increments_post_body_without_mutating_options() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        page = body["pagination"]["page"]
        assert body["searchCriteria"] == {"msc": [752]}
        return httpx.Response(
            200, json={"pagination": {"nextPage": page < 2}, "data": [{"id": page}]}
        )

    server = Server(answer)
    options = {
        "rows": "data",
        "body": {"pagination": {"page": 1, "size": 1000}, "searchCriteria": {"msc": [752]}},
        "paginate": {"more": "pagination.nextPage", "page": "pagination.page", "delay_seconds": 0},
    }
    fetched = await server.reader(AccessKind.REQUEST).fetch(
        source(AccessKind.REQUEST, format=DataFormat.JSON, options=options), TimeRange()
    )
    assert json.loads(fetched.content)["data"] == [{"id": 1}, {"id": 2}]
    assert [r.method for r in server.requests] == ["POST", "POST"]
    assert options["body"]["pagination"]["page"] == 1


async def test_pagination_limit_is_recorded_as_source_error(world: World) -> None:
    server = Server(lambda request: httpx.Response(200, json={"data": [], "next": "again"}))
    world.service.readers = HttpSourceReaders(
        create_client(httpx.MockTransport(server)), world.clock, allow_private=True
    )
    registered = await world.register(
        format=DataFormat.JSON,
        options={
            "rows": "data",
            "paginate": {"token": "next", "param": "cursor", "max_pages": 2, "delay_seconds": 0},
        },
    )
    with pytest.raises(Unavailable, match="max_pages"):
        await world.service.refresh(registered.id)
    assert "max_pages (2)" in (await world.service.get(registered.id)).last_error
    assert len(server.requests) == 2


async def test_post_probe_fields_include_array_indexes() -> None:
    updated = "2026-01-01"

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert json.loads(request.content) == {"size": 1}
        assert request.headers["x-key"] == "test"
        return httpx.Response(
            200, json={"pagination": {"total": 10}, "data": [{"id": "a", "updated": updated}]}
        )

    server = Server(answer)
    declared = source(
        options={
            "headers": {"X-Key": "test"},
            "probe": {
                "url": "https://x.test/search",
                "method": "POST",
                "body": {"size": 1},
                "fields": ["pagination.total", "data.0.id", "data.0.updated"],
            },
        }
    )
    reader = server.reader()
    first = await reader.probe(declared)
    assert json.loads(first) == [10, "a", "2026-01-01"]
    updated = "2026-01-02"
    assert await reader.probe(declared) != first


async def test_url_page_pagination_starts_from_params_and_keeps_top_level_arrays() -> None:
    server = Server(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "page": int(request.url.params["page"]),
                    "more": int(request.url.params["page"]) < 4,
                }
            ],
        )
    )
    fetched = await server.reader().fetch(
        source(
            address="https://x.test/search?page=1",
            format=DataFormat.JSON,
            options={
                "params": {"page": 3},
                "paginate": {
                    "more": "0.more",
                    "page": "page",
                    "delay_seconds": 0,
                },
            },
        ),
        TimeRange(),
    )
    assert json.loads(fetched.content) == [{"page": 3, "more": True}, {"page": 4, "more": False}]


@pytest.mark.parametrize(
    "paginate",
    [
        {"token": "next"},
        {"token": "next", "param": "cursor", "max_pages": 101},
        {"more": "more", "page": "page", "delay_seconds": -1},
    ],
)
async def test_malformed_pagination_fails_before_sending(paginate: dict[str, Any]) -> None:
    server = Server(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(Invalid, match="Example paginate"):
        await server.reader().fetch(
            source(format=DataFormat.JSON, options={"paginate": paginate}), TimeRange()
        )
    assert not server.requests


async def test_paginated_get_only_uses_a_declared_probe() -> None:
    server = Server(lambda request: httpx.Response(200, headers={"ETag": "first-page"}, json=5))
    options: dict[str, Any] = {"paginate": {"token": "next", "param": "cursor"}}
    reader = server.reader()
    assert await reader.probe(source(options=options)) is None
    assert not server.requests

    options["probe"] = {"url": "https://x.test/version"}
    token = await reader.probe(source(options=options))
    assert token is not None and token.startswith("sha256:")
    [request] = server.requests
    assert (request.method, str(request.url)) == ("GET", "https://x.test/version")


@pytest.mark.parametrize("last_page", [{"more": False}, {"more": None}, {}])
async def test_page_pagination_requires_more_on_every_page(last_page: dict[str, Any]) -> None:
    answers = iter(
        [
            {"data": [], "pagination": {"more": True}},
            {"data": [], "pagination": last_page},
        ]
    )
    server = Server(lambda request: httpx.Response(200, json=next(answers)))
    declared = source(
        format=DataFormat.JSON,
        options={
            "rows": "data",
            "paginate": {"more": "pagination.more", "page": "page", "delay_seconds": 0},
        },
    )
    if last_page:
        await server.reader().fetch(declared, TimeRange())
    else:
        with pytest.raises(Invalid, match="no field 'pagination.more'"):
            await server.reader().fetch(declared, TimeRange())
    assert len(server.requests) == 2
