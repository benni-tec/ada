"""Cases as a data source: a case type's cases, step events and results as snapshots
(read through the case repository, no network), their columns derived from the case type
and its models, the project boundary, and push freshness on every save."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from fastapi.testclient import TestClient

from ada.adapters.duckdb.store import DuckDbAnalysisStore
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.repositories import (
    MemoryCaseRepository,
    MemoryDataSourceRepository,
    MemoryOperatorRepository,
    MemoryProjectRepository,
    MemorySnapshotRepository,
    MemorySourceCheckLog,
    MemorySourceLocks,
    MemoryStatisticalModelRepository,
    MemoryStore,
)
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.secrets.fernet import FernetSecretBox
from ada.adapters.sources.cases import CaseSourceReader, CaseSourceReaders
from ada.adapters.transactions import PendingWork
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.analysis import Query, Rows
from ada.core.models.cases import CaseType, Field, FieldType
from ada.core.models.errors import Invalid
from ada.core.models.projects import Project
from ada.core.models.schema import ColumnType, GeoRole, Roles, Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
)
from ada.core.models.time import TimeRange
from ada.core.services.cases.service import Cases
from ada.core.services.sources.service import WHOLE_SOURCE, DataSources, source_operator_id
from ada.core.services.statistical_models.pathway_kind import PathwayKind
from ada.core.services.statistical_models.service import StatisticalModels
from api_support import Overrides, new_project, send, serve
from api_support import dispatcher as recorded
from fakes import FakeExplorer, FakeSourceReaders, FixedClock
from test_cases import EARLY, OVERDUE

pytestmark = pytest.mark.anyio

ACTOR = Actor(kind=ActorKind.USER, name="test")


class World:
    """One project with the pathway model and its case type, the cases service, and the
    source service reading cases sources into a real analysis store."""

    def __init__(self, data_dir: Path) -> None:
        self.memory = MemoryStore()
        self.clock = FixedClock()
        self.project = Project(id=uuid7(), name="Nordic cancer care", created_at=self.clock.now())
        self.memory.projects[self.project.id] = self.project
        self.repo = MemoryCaseRepository(self.memory)
        models = MemoryStatisticalModelRepository(self.memory)
        projects = MemoryProjectRepository(self.memory)
        self.models = StatisticalModels(models, projects, self.repo, None, self.clock)  # type: ignore[arg-type]
        self.dispatcher = RecordingTaskDispatcher()
        self.after_commit = PendingWork()
        self.cases = Cases(
            self.repo,
            models,
            self.clock,
            MemoryDataSourceRepository(self.memory),
            self.dispatcher,
            self.after_commit,
        )
        self.reader = CaseSourceReader(self.repo, models, self.clock)
        self.store = DuckDbAnalysisStore(data_dir)
        self.sources = DataSources(
            projects=projects,
            sources=MemoryDataSourceRepository(self.memory),
            operators=MemoryOperatorRepository(self.memory),
            snapshots=MemorySnapshotRepository(self.memory),
            readers=CaseSourceReaders(FakeSourceReaders(), self.reader),
            checks=MemorySourceCheckLog(self.memory),
            store=self.store,
            events=MemoryEventBus(),
            clock=self.clock,
            locks=MemorySourceLocks(),
            explorer=FakeExplorer(),
            secrets=FernetSecretBox(None),
            public_url=None,
            cases=self.repo,
            statistical=models,
        )

    async def pathway(self) -> CaseType:
        version = await self.models.create_pathway_model(self.project.id, ACTOR)
        model = await self.models.get(version.model_id)
        assert model.case_type_id is not None
        return await self.cases.get_type(model.case_type_id)

    async def register(self, case_type: CaseType, **changes: Any) -> DataSource:
        arguments: dict[str, Any] = {
            "name": "Pathway cases",
            "access_kind": AccessKind.CASES,
            "address": str(case_type.id),
            "format": DataFormat.CSV,
        }
        return await self.sources.register(self.project.id, **(arguments | changes))

    async def rows(self, source: DataSource) -> list[dict[str, Any]]:
        """The source's whole current snapshot, fetched now, as records."""
        await self.sources.refresh(source.id, force=True)
        operator_id = source_operator_id(source)
        current = await MemorySnapshotRepository(self.memory).current(operator_id, WHOLE_SOURCE)
        assert current is not None
        query = Query(sql="SELECT * FROM t ORDER BY ALL", relations={"t": current.location})
        found: Rows = await self.store.run(query, 1000)
        self.columns = {column.name: column.type for column in found.columns}
        return [dict(zip(self.columns, row, strict=True)) for row in found.rows]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path / "data")


async def test_the_cases_table_has_every_field_with_day_maps_flattened(world: World) -> None:
    case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    await world.cases.put_case(case_type.id, "SYN-0002", EARLY, ACTOR)
    await world.cases.put_case(case_type.id, "SYN-0002", EARLY, ACTOR)
    source = await world.register(case_type)

    # Read as Parquet whatever was asked, and kept fresh by push.
    assert (source.format, source.freshness.kind) == (DataFormat.PARQUET, FreshnessKind.PUSH)
    declared = source.declared_schema
    assert declared is not None and declared.roles.time is not None
    assert (declared.roles.time.start, declared.roles.time.end) == ("updated_at", "updated_at")
    [first, second] = await world.rows(source)
    assert [c.name for c in declared.columns] == list(world.columns)
    assert (first["key"], first["revision"], second["revision"]) == ("SYN-0001", 1, 2)
    # The case type's own field, which no model reads, is a column too.
    assert (first["county"], second["county"]) == ("Pirkanmaa", "Lappi")
    assert first["presentation"] == "lung_symptoms_smoker,lung_imaging"
    assert first["days_workup_to_treatment"] == 12
    # A step the case has not reached is null.
    assert second["days_workup_to_treatment"] is None
    assert world.columns["days_symptoms_to_contact"] == "integer"
    assert world.columns["updated_at"] == "timestamp"
    assert first["referred_by"] is None


async def test_a_field_added_later_appears_as_a_column(world: World) -> None:
    case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    source = await world.register(case_type)
    grown = (*case_type.fields, Field(name="clinic", type=FieldType.TEXT))
    await world.cases.update_type(case_type.id, fields=grown)
    await world.cases.put_case(case_type.id, "SYN-0001", {**OVERDUE, "clinic": "Tays"}, ACTOR)
    [row] = await world.rows(source)
    assert row["clinic"] == "Tays"


async def test_the_events_table_has_a_row_per_step_event(world: World) -> None:
    case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", EARLY, ACTOR)
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    source = await world.register(case_type, options={"table": "events"})
    assert source.declared_schema is not None
    assert source.declared_schema.roles.time is not None
    assert source.declared_schema.roles.time.start == "recorded_at"
    rows = await world.rows(source)
    events = (await world.cases.get_case(case_type.id, "SYN-0001")).events
    assert len(rows) == len(events)
    assert set(world.columns) == {"key", "field", "level", "old", "new", "recorded_at"}
    finished = [r for r in rows if r["level"] == "workup_to_treatment"]
    assert [(r["key"], r["field"], r["old"], r["new"]) for r in finished] == [
        ("SYN-0001", "days", None, "12")
    ]
    county = [r for r in rows if r["field"] == "county"]
    assert {(r["old"], r["new"]) for r in county} == {(None, '"Lappi"'), ('"Lappi"', '"Pirkanmaa"')}


async def test_the_results_table_prefixes_each_section_column_by_model_kind(
    world: World,
) -> None:
    case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    source = await world.register(case_type, options={"table": "results"})
    declared = source.declared_schema
    assert declared is not None and declared.column("patient_pathway_days_behind") is not None
    [row] = await world.rows(source)
    assert (row["key"], row["model"], row["trigger"], row["version"]) == (
        "SYN-0001",
        "Patient pathway model",
        "auto",
        1,
    )
    assert row["summary"] == "Treatment start overdue by 3 days"
    assert row["status"] == "urgent"
    assert (row["open"], row["overdue_by"], row["due_in"]) == (True, 3, None)
    assert row["patient_pathway_treatment_start_status"] == "overdue"
    assert row["patient_pathway_treatment_start_by"] == 3
    assert world.columns["patient_pathway_days_behind"] == ColumnType.INTEGER


async def test_a_model_declares_every_column_its_sections_have(world: World) -> None:
    case_type = await world.pathway()
    saved = await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    early = await world.cases.put_case(case_type.id, "SYN-0002", EARLY, ACTOR)
    model = await world.models.get(saved.results[0].model_id)
    version = await world.models.version(model.id, model.latest_version)
    declared = {c.name for c in PathwayKind().columns(version)}
    for result in (saved.results[0], early.results[0]):
        assert set(result.section.columns) <= declared


async def test_declared_roles_are_kept(world: World) -> None:
    case_type = await world.pathway()
    geo = GeoRole(code="county", system="name", level="wellbeing_services_county")
    source = await world.register(case_type, declared_schema=Schema(roles=Roles(geo=geo)))
    assert source.declared_schema is not None
    assert source.declared_schema.roles.geo == geo
    assert source.declared_schema.roles.time is not None


async def test_saving_a_case_marks_its_push_sources_stale(world: World) -> None:
    case_type = await world.pathway()
    pushed = await world.register(case_type)
    results = await world.register(case_type, options={"table": "results"})
    manual = await world.register(case_type, freshness=FreshnessPolicy())
    other = await world.cases.create_type(
        world.project.id,
        "Other",
        "",
        (Field(name="site", type=FieldType.TEXT),),
        ACTOR,
    )
    elsewhere = await world.register(other)

    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    await world.cases.put_case(case_type.id, "SYN-0002", EARLY, ACTOR)
    # Nothing goes out before the commit, and once per source however much was saved.
    assert world.dispatcher.refreshes == []
    await world.after_commit.run()
    assert sorted(world.dispatcher.refreshes) == sorted([(pushed.id, True), (results.id, True)])
    assert manual.id not in {id for id, _ in world.dispatcher.refreshes}
    assert elsewhere.id not in {id for id, _ in world.dispatcher.refreshes}


async def test_a_result_on_request_marks_the_sources_stale(world: World) -> None:
    case_type = await world.pathway()
    saved = await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    source = await world.register(case_type, options={"table": "results"})
    # A unit of work of its own, as an evaluation over REST or MCP is.
    world.cases = Cases(
        world.repo,
        MemoryStatisticalModelRepository(world.memory),
        world.clock,
        MemoryDataSourceRepository(world.memory),
        world.dispatcher,
        world.after_commit,
    )
    await world.after_commit.run()
    world.dispatcher.refreshes.clear()
    await world.cases.evaluate(case_type.id, "SYN-0001", saved.results[0].model_id, ACTOR)
    await world.after_commit.run()
    assert world.dispatcher.refreshes == [(source.id, True)]


async def test_another_projects_case_type_is_refused(world: World) -> None:
    case_type = await world.pathway()
    stranger = Project(id=uuid7(), name="Elsewhere", created_at=world.clock.now())
    world.memory.projects[stranger.id] = stranger
    with pytest.raises(Invalid, match="another project"):
        await world.sources.register(
            stranger.id, "Theirs", AccessKind.CASES, str(case_type.id), DataFormat.PARQUET
        )
    # The reader checks it too, for a source that got past registration somehow.
    source = DataSource(
        id=uuid7(),
        project_id=stranger.id,
        name="Theirs",
        access_kind=AccessKind.CASES,
        address=str(case_type.id),
        format=DataFormat.PARQUET,
        created_at=world.clock.now(),
    )
    with pytest.raises(Invalid, match="another project"):
        await world.reader.fetch(source, TimeRange())


async def test_an_unknown_table_or_address_is_refused(world: World) -> None:
    case_type = await world.pathway()
    with pytest.raises(Invalid, match="options.table"):
        await world.register(case_type, options={"table": "patients"})
    with pytest.raises(Invalid, match="case type's id"):
        await world.register(case_type, address="pathway")
    source = await world.register(case_type)
    with pytest.raises(Invalid, match="one table of one case type"):
        await world.sources.update(source.id, source.revision, options={"table": "events"})


# Over REST: a registered cases source is refreshed after a save commits.


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


def test_rest_saving_a_case_queues_a_refresh_of_its_source(client: TestClient) -> None:
    project = new_project(client, "Nordic cancer care")
    send(client, "POST", f"/projects/{project['id']}/models/pathway", None, 201)
    [case_type] = send(client, "GET", f"/projects/{project['id']}/case-types")
    source = send(
        client,
        "POST",
        f"/projects/{project['id']}/sources",
        {
            "name": "Pathway cases",
            "access_kind": "cases",
            "address": case_type["id"],
            "format": "parquet",
            "freshness": {"kind": "push"},
        },
        201,
    )
    send(client, "PUT", f"/case-types/{case_type['id']}/cases/SYN-0042", {"values": OVERDUE})
    assert (source["id"], True) in [(str(id), force) for id, force in recorded(client).refreshes]
