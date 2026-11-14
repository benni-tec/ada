"""Sources: registering, refreshing by freshness policy, the HTTP readers, shaping an answer
into a table, and the example registrations against their recorded answers."""

import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from dishka import Provider, Scope
from dishka.integrations.fastapi import FastapiProvider

import factories
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
from ada.adapters.sources.document import DocumentReader
from ada.adapters.sources.examples import (
    EXAMPLES,
    NORDCAN_LUNG_SURVIVAL,
    SOTKANET_BREAST_SCREENING,
    STATFIN_CANCER_DEATHS,
    ExampleSource,
)
from ada.adapters.sources.http import (
    USER_AGENT,
    HttpSourceReaders,
    SourceUnavailable,
    create_client,
)
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import ActorKind
from ada.core.models.analysis import FetchedData
from ada.core.models.base import Id
from ada.core.models.errors import Conflict, Invalid, NotFound, Unavailable
from ada.core.models.events import EventType
from ada.core.models.operators import OperatorKind, operator_identity
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
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sources import SourceService
from ada.core.services.sources.service import DataSources, source_operator_id
from ada.core.services.sources.shaping import shape
from conftest import settings_in
from fakes import (
    RECORDINGS,
    FakeAnalysisStore,
    FakePageReader,
    FakeSourceReader,
    FakeSourceReaders,
    FixedClock,
    Replay,
)
from memory import MemoryBackground, MemoryRepositories

pytestmark = pytest.mark.anyio

CSV = b"region,value\nHelsinki,74.3\n"


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
    memory: MemoryStore, readers: SourceReaders, store: FakeAnalysisStore, clock: FixedClock
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


async def test_register_source_keeps_provenance(world: World) -> None:
    provenance = Provenance(
        publisher="THL",
        licence="unknown",
        found_by=FoundBy(query="stroke survival", scope="web"),
        note="no licence on the page",
    )

    source = await world.register(provenance=provenance)

    assert (await world.service.get(source.id)).provenance == provenance
    assert (await world.register()).provenance is None


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


# Document sources


PAGE = "https://example.test/page"


@pytest.fixture
def pages() -> FakePageReader:
    return FakePageReader(text="Indicator 3625", rows=[{"county": "Uusimaa", "rate": 74.3}])


@pytest.fixture
async def documents(world: World, pages: FakePageReader) -> World:
    readers = FakeSourceReaders({AccessKind.DOCUMENT: DocumentReader(pages, world.clock)})
    world.service, world.events = data_sources(world.memory, readers, world.store, world.clock)
    return world


async def test_document_source_extracts_rows(documents: World, pages: FakePageReader) -> None:
    extract = {"instruction": "the rate per county", "columns": ["county", "rate"]}
    source = await documents.register(
        access_kind=AccessKind.DOCUMENT,
        address=PAGE,
        format=DataFormat.JSON,
        options={"extract": extract},
    )

    await documents.service.refresh(source.id)

    [written] = documents.store.written
    assert json.loads(written.content) == [{"county": "Uusimaa", "rate": 74.3}]
    assert pages.calls == [("extract", (PAGE, "the rate per county", ("county", "rate")))]
    assert [s.origin for s in documents.current(source)] == [PAGE]


async def test_document_source_without_extract_is_one_page_row(documents: World) -> None:
    source = await documents.register(
        access_kind=AccessKind.DOCUMENT, address=PAGE, format=DataFormat.JSON
    )

    await documents.service.refresh(source.id)

    [written] = documents.store.written
    assert json.loads(written.content) == [{"url": PAGE, "title": None, "text": "Indicator 3625"}]


@pytest.mark.parametrize(
    ("kind", "ttl"),
    [(FreshnessKind.TTL, 60), (FreshnessKind.PROBE, 60), (FreshnessKind.TTL, None)],
)
async def test_document_source_rejects_ttl(
    documents: World, kind: FreshnessKind, ttl: int | None
) -> None:
    message = (
        "A document source refreshes only by hand or when its monitor fires"
        " (freshness manual or push)"
    )
    policy = FreshnessPolicy(kind=kind, ttl_seconds=ttl)
    arguments: dict[str, Any] = {
        "access_kind": AccessKind.DOCUMENT,
        "address": PAGE,
        "format": DataFormat.JSON,
    }
    with pytest.raises(Invalid) as error:
        await documents.register(**arguments, freshness=policy)
    assert str(error.value) == message

    source = await documents.register(**arguments)
    with pytest.raises(Invalid) as error:
        await documents.service.update(source.id, source.revision, freshness=policy)
    assert str(error.value) == message


async def test_document_source_cannot_become_ttl_by_update(documents: World) -> None:
    source = await documents.register(
        access_kind=AccessKind.DOCUMENT,
        address=PAGE,
        format=DataFormat.JSON,
        freshness=FreshnessPolicy(kind=FreshnessKind.PUSH),
    )

    with pytest.raises(Invalid, match="freshness manual or push"):
        await documents.service.update(source.id, source.revision, freshness=probing())

    assert (await documents.service.get(source.id)).freshness.kind is FreshnessKind.PUSH


async def test_document_source_must_be_json(documents: World) -> None:
    with pytest.raises(Invalid, match="json"):
        await documents.register(access_kind=AccessKind.DOCUMENT, address=PAGE)


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

    await repository.set_monitor(source.id, "mon_1", "sealed")
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
        assert isinstance(readers, HttpSourceReaders)
        async with container() as request:
            service = await request.get(SourceService)
            assert isinstance(service, DataSources)
            # The readers, and with them the HTTP client, are shared by every request.
            assert service.readers is readers
    finally:
        await container.close()
    assert readers.readers[AccessKind.URL].client.is_closed


# The HTTP readers


class Server:
    """Answers with `handler` and keeps every request it saw."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def reader(self, kind: AccessKind = AccessKind.URL):  # noqa: ANN201
        return HttpSourceReaders(create_client(httpx.MockTransport(self)), FixedClock()).for_kind(
            kind
        )


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
    readers = HttpSourceReaders(create_client(httpx.MockTransport(replay)), clock)
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
