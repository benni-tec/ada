"""The example registrations, refreshed through the recorded answers of their APIs."""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

import factories
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemoryStore,
)
from ada.adapters.sources.examples import (
    EXAMPLES,
    NORDCAN_LUNG_SURVIVAL,
    SOTKANET_BREAST_SCREENING,
    STATFIN_CANCER_DEATHS,
    ExampleSource,
)
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.core.models.analysis import FetchedData
from ada.core.models.base import Id
from ada.core.models.runs import Snapshot
from ada.core.models.sources import DataSource
from ada.core.services.sources.service import DataSources, source_operator_id
from fakes import FakeAnalysisStore, FixedClock

pytestmark = pytest.mark.anyio

RECORDINGS = Path(__file__).parent / "recordings"


class Replay:
    """Answers the requests that were recorded and fails every other one, so a test can
    never reach the network."""

    def __init__(self) -> None:
        index = json.loads((RECORDINGS / "sources.json").read_text())
        self.exchanges: list[dict[str, Any]] = index["exchanges"]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for exchange in self.exchanges:
            if exchange["method"] == request.method and _same(exchange["url"], request.url):
                if "request" in exchange:
                    expected = json.loads((RECORDINGS / exchange["request"]).read_bytes())
                    assert json.loads(request.content) == expected
                return httpx.Response(
                    exchange["status"],
                    headers={"Content-Type": exchange["content_type"]},
                    content=(RECORDINGS / exchange["body"]).read_bytes(),
                )
        raise AssertionError(f"No recording for {request.method} {request.url}")


def _same(recorded: str, url: httpx.URL) -> bool:
    expected = httpx.URL(recorded)
    return (expected.host, expected.path, sorted(expected.params.multi_items())) == (
        url.host,
        url.path,
        sorted(url.params.multi_items()),
    )


@dataclass
class World:
    service: DataSources
    memory: MemoryStore
    store: FakeAnalysisStore
    replay: Replay
    clock: FixedClock
    project_id: Id

    async def refresh(self, example: ExampleSource) -> tuple[DataSource, Snapshot, FetchedData]:
        source = await self.service.register(self.project_id, **example.registration())
        result = await self.service.refresh(source.id)
        assert result.changed
        [snapshot_id] = result.snapshot_ids
        [written] = self.store.written
        return await self.service.get(source.id), self.memory.snapshots[snapshot_id], written


@pytest.fixture
async def world() -> World:
    memory = MemoryStore()
    clock = FixedClock()
    replay = Replay()
    project = factories.project()
    await MemoryProjectRepository(memory).add(project)
    store = FakeAnalysisStore()
    service = DataSources(
        projects=MemoryProjectRepository(memory),
        sources=MemoryDataSourceRepository(memory),
        operators=MemoryOperatorRepository(memory),
        snapshots=MemorySnapshotRepository(memory),
        readers=HttpSourceReaders(create_client(httpx.MockTransport(replay)), clock),
        checks=MemorySourceCheckLog(memory),
        store=store,
        events=MemoryEventBus(),
        clock=clock,
    )
    return World(service, memory, store, replay, clock, project.id)


def test_every_recording_is_small() -> None:
    for path in RECORDINGS.iterdir():
        assert path.stat().st_size < 200_000, path.name


async def test_sotkanet_breast_screening(world: World) -> None:
    source, snapshot, written = await world.refresh(SOTKANET_BREAST_SCREENING)

    # The probe ran first and its token is the indicator's data-updated date.
    assert [r.method + " " + r.url.path for r in world.replay.requests] == [
        "GET /rest/1.1/indicators/3621",
        "GET /rest/1.1/json",
    ]
    assert source.last_probe_token == "2026-06-12"
    rows = json.loads(written.content)
    assert len(rows) == 880
    assert rows[0] == {
        "indicator": 3621,
        "region": 52,
        "year": 2023,
        "gender": "total",
        "value": 86.6,
        "count": 560,
    }
    assert {row["year"] for row in rows} == {2023, 2024}
    assert written.origin == SOTKANET_BREAST_SCREENING.address
    assert snapshot.operator_id == source_operator_id(source)
    assert snapshot.location == f"memory://{world.project_id}/{snapshot.content_hash}"


async def test_sotkanet_is_not_fetched_again_while_its_data_is_unchanged(world: World) -> None:
    source, _, _ = await world.refresh(SOTKANET_BREAST_SCREENING)
    world.clock.advance(days=1)

    result = await world.service.refresh(source.id)

    assert not result.changed
    assert [r.url.path for r in world.replay.requests[2:]] == ["/rest/1.1/indicators/3621"]


async def test_statistics_finland_cancer_deaths(world: World) -> None:
    _, snapshot, written = await world.refresh(STATFIN_CANCER_DEATHS)

    [request] = world.replay.requests
    assert request.method == "POST"
    table = list(csv.DictReader(io.StringIO(written.content.decode())))
    assert list(table[0]) == list(STATFIN_CANCER_DEATHS.options["csv"]["columns"])
    # 26 areas, from the whole country to Åland, for four causes.
    assert len(table) == 26 * 4
    lung = next(
        row for row in table if row["county"] == "WHOLE COUNTRY" and row["cause"].startswith("11 ")
    )
    assert (lung["deaths_2022"], lung["deaths_2023"], lung["deaths_2024"]) == (
        "2447",
        "2256",
        "2317",
    )
    assert {row["county"] for row in table} >= {"HVA90 City of Helsinki", "HVA91 Åland"}
    assert snapshot.parameters_key == ""


async def test_nordcan_lung_survival(world: World) -> None:
    _, _, written = await world.refresh(NORDCAN_LUNG_SURVIVAL)

    rows = json.loads(written.content)
    assert len(rows) == 76
    assert {row["country"] for row in rows} == {"Denmark", "Finland", "Norway", "Sweden"}
    # The spec's Nordic comparison: Finland 17.9 (men) and 30.8 (women), 2020-2024.
    finland = {
        row["sex"]: row["survival"]
        for row in rows
        if row["country"] == "Finland" and row["period"] == "2020-2024"
    }
    assert finland == {1: 17.9, 2: 30.8}


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.name.split(" (")[0])
async def test_each_example_declares_exactly_the_columns_it_produces(
    world: World, example: ExampleSource
) -> None:
    _, _, written = await world.refresh(example)

    if written.format.value == "json":
        columns = list(json.loads(written.content)[0])
    else:
        columns = next(csv.reader(io.StringIO(written.content.decode())))
    assert example.declared_schema is not None
    assert columns == [column.name for column in example.declared_schema.columns]
