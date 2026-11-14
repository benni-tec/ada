"""Reports: the component tree and the version arithmetic, the services on the memory
repositories (with fake runs and dashboards from reports_support), the MCP tools and the
REST routes, and concurrent versions on PostgreSQL."""

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError

import db_helpers
import factories
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Conflict, Invalid
from ada.core.models.events import EventType
from ada.core.models.operators import OperatorKind
from ada.core.models.reports import ReportSource, ReportVersion, TemplateKind, VersionBump
from ada.core.models.runs import Run
from ada.core.models.time import TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.repositories import OperatorRepository, WidgetRepository
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.ports.runs import RunService
from ada.core.services.reports import content as tree
from ada.core.services.reports.versions import State, decide, required
from api_support import Overrides, call, mcp_client, send, serve
from conftest import settings_in
from memory import MemoryBackground, memory_adapters
from reports_support import (
    FETCHED_A,
    FETCHED_B,
    YEAR_2024,
    Executed,
    ReportFakes,
    Scene,
    blocks,
    heading,
    published,
    seed,
    shows,
    text,
)

pytestmark = pytest.mark.anyio

AGENT = factories.AGENT


# The tree and the versions


def parse(*blocks: object, kind: tree.Tree = tree.Tree.REPORT) -> list[object]:
    return tree.dump(tree.parse({"blocks": list(blocks)}, kind))


def test_a_tree_is_stored_with_its_defaults_and_its_widgets_once_in_reading_order() -> None:
    first, second = uuid7(), uuid7()
    content = {
        "blocks": [
            {"type": "heading", "text": "Screening gap"},
            {"type": "widget", "widget_id": str(second)},
            {"type": "section", "blocks": [{"type": "widget", "widget_id": str(first)}]},
            {"type": "callout", "text": "Below target"},
            {"type": "widget", "widget_id": str(second)},
        ]
    }

    parsed = tree.parse(content, tree.Tree.REPORT)

    assert tree.dump(parsed)[:4] == [
        {"type": "heading", "text": "Screening gap", "level": 2},
        {"type": "widget", "widget_id": str(second), "caption": ""},
        {
            "type": "section",
            "title": "",
            "blocks": [{"type": "widget", "widget_id": str(first), "caption": ""}],
        },
        {"type": "callout", "tone": "note", "title": "", "text": "Below target"},
    ]
    assert tree.widget_ids(parsed) == [second, first]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        # Data on a static block: only widgets show data.
        (blocks({"type": "callout", "text": "x", "value": 81.5}), "blocks[0].value: not a field"),
        (
            blocks({"type": "text", "text": "a"}, {"type": "section", "blocks": [{"text": 5}]}),
            "blocks[1].blocks[0]: a block needs a `type`",
        ),
        ({"blocks": [], "sources": []}, "`sources` is generated"),
    ],
)
def test_a_wrong_tree_is_invalid_and_the_problem_located(content: Any, message: str) -> None:
    with pytest.raises(Invalid, match=re.escape(message)):
        tree.parse(content, tree.Tree.REPORT)


def test_a_template_places_slots_that_filling_replaces() -> None:
    with pytest.raises(Invalid, match="names a `slot`"):
        parse({"type": "widget", "widget_id": str(uuid7())}, kind=tree.Tree.TEMPLATE)
    with pytest.raises(Invalid, match="more than once"):
        parse(
            {"type": "widget", "slot": "g"},
            {"type": "widget", "slot": "g"},
            kind=tree.Tree.TEMPLATE,
        )
    widget_id = uuid7()
    template = tree.parse(
        blocks({"type": "section", "title": "Gap", "blocks": [{"type": "widget", "slot": "g"}]}),
        tree.Tree.TEMPLATE,
    )

    filled = tree.fill(template, {"g": widget_id})

    assert (tree.widget_ids(filled), tree.slot_names(filled)) == ([widget_id], [])


def test_the_version_level_follows_from_what_changed() -> None:
    run = uuid7()

    def state(**changes: object) -> State:
        base: dict[str, object] = {
            "operators": frozenset({"op_a"}),
            "run_id": run,
            "time_range": TimeRange(),
            "blocks": [{"type": "text", "text": "a"}],
        }
        return State(**(base | changes))  # type: ignore[arg-type]

    assert required(state(), state()) is None
    assert required(state(), state(blocks=[{"type": "text", "text": "b"}])) is VersionBump.PATCH
    assert required(state(), state(run_id=uuid7())) is VersionBump.MINOR
    assert required(state(), state(time_range=TimeRange(start=date(2024, 1, 1)))) is (
        VersionBump.MINOR
    )
    # The pipelines outrank the run: a new run with new widgets is still major.
    assert required(state(), state(operators=frozenset(), run_id=uuid7())) is VersionBump.MAJOR
    # A given level may be higher, never lower.
    assert decide("1.9.3", VersionBump.PATCH, VersionBump.MINOR) == "1.10.0"
    with pytest.raises(Invalid, match="too small"):
        decide("1.0.0", VersionBump.MINOR, VersionBump.PATCH)


# The services


@pytest.fixture
async def container(unreachable_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = create_container(
        unreachable_settings, FastapiProvider(), *memory_adapters(), Overrides(), ReportFakes()
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def scene(container: AsyncContainer) -> Scene:
    return await seed(container)


class Calls:
    """Each call is one unit of work, as a request or tool call would be."""

    def __init__(self, container: AsyncContainer) -> None:
        self.container = container

    async def reports(self, method: str, *args: Any, **kwargs: Any) -> Any:
        async with self.container() as request:
            service = await request.get(ReportService)
            return await getattr(service, method)(*args, **kwargs)

    async def templates(self, method: str, *args: Any, **kwargs: Any) -> Any:
        async with self.container() as request:
            service = await request.get(TemplateService)
            return await getattr(service, method)(*args, **kwargs)

    async def run(self, project_id: UUID, time_range: TimeRange | None = None) -> Run:
        async with self.container() as request:
            return await (await request.get(RunService)).start(project_id, AGENT, time_range)

    async def create(self, scene: Scene, content: dict[str, Any], **kwargs: Any) -> ReportVersion:
        run = kwargs.pop("run", None) or await self.run(scene.project.id)
        kwargs.setdefault("session_id", scene.session.id)
        return await self.reports(
            "create",
            scene.project.id,
            kwargs.pop("name", "Findings"),
            content,
            run.id,
            kwargs.pop("time_range", run.time_range),
            AGENT,
            **kwargs,
        )

    async def add(
        self, version: ReportVersion, content: dict[str, Any], run: Run | None = None, **kwargs: Any
    ) -> ReportVersion:
        if run is None:
            run = await self.run_of(version.run_id)
        return await self.reports(
            "add_version", version.report_id, content, run.id, run.time_range, AGENT, **kwargs
        )

    async def run_of(self, run_id: UUID) -> Run:
        async with self.container() as request:
            return await (await request.get(RunService)).get(run_id)


@pytest.fixture
def calls(container: AsyncContainer) -> Calls:
    return Calls(container)


# What a version's copy of a widget keeps from the original.
SHOWN = {"operator_id", "inputs", "type", "spec", "title", "note", "verdict"}


async def shown(container: AsyncContainer, version: ReportVersion) -> list[Widget]:
    """The widgets a version shows, in reading order."""
    async with container() as request:
        widgets = await request.get(WidgetRepository)
        ids = tree.widget_ids(tree.stored_blocks(version.content))
        return [await widgets.get(id) for id in ids]


async def test_a_report_starts_at_1_0_0_and_freezes_each_pipeline_once_in_its_run(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    run = await calls.run(scene.project.id, YEAR_2024)
    content = blocks(heading("Gap"), shows(scene.value), shows(scene.table), shows(scene.chart))

    version = await calls.create(scene, content, run=run)

    assert (version.version, version.run_id, version.time_range) == ("1.0.0", run.id, YEAR_2024)
    # It shows copies of its own, as a dashboard does: changing the originals later does not
    # change what the version shows.
    copies = await shown(container, version)
    assert version.content["blocks"][1] == {
        "type": "widget",
        "widget_id": str(copies[0].id),
        "caption": "",
    }
    originals = (scene.value, scene.table, scene.chart)
    assert [copy.copied_from for copy in copies] == [widget.id for widget in originals]
    assert [copy.model_dump(include=SHOWN) for copy in copies] == [
        widget.model_dump(include=SHOWN) for widget in originals
    ]
    assert {copy.session_id for copy in copies} == {None}
    report = await calls.reports("get", version.report_id)
    assert (report.name, report.session_id, report.dashboard_id) == (
        "Findings",
        scene.session.id,
        None,
    )
    assert report.latest_version_id == version.id
    # value and table read the same operator: executed once.
    executed = (await container.get(Executed)).calls
    assert executed == [(run.id, scene.cleaned.id), (run.id, scene.joined.id)]
    pinned = await calls.run_of(run.id)
    assert set(pinned.snapshots) == {scene.operator_a.id, scene.operator_b.id}

    async with container() as request:
        renamed = scene.value.model_copy(update={"title": "Newest coverage"})
        await (await request.get(WidgetRepository)).save(renamed)
    # Only a widget's settings changed: a patch, and the first version shows what it did.
    assert (await calls.add(version, content)).version == "1.0.1"
    assert (await shown(container, version))[0].title == "Latest coverage"


async def test_a_report_needs_one_owner_widgets_of_its_project_and_a_fitting_run(
    calls: Calls, scene: Scene
) -> None:
    value = blocks(shows(scene.value))
    with pytest.raises(Invalid, match="exactly one session or one dashboard"):
        await calls.create(scene, value, dashboard_id=scene.dashboard.id)
    with pytest.raises(Invalid, match="another project"):
        await calls.create(scene, blocks(shows(scene.stranger)))
    with pytest.raises(Invalid, match="does not exist"):
        await calls.create(scene, blocks(shows(uuid7())))
    with pytest.raises(Invalid, match="another project"):
        await calls.create(scene, value, run=await calls.run(scene.other_project.id))
    with pytest.raises(Invalid, match="was started for 2024-01-01 to 2024-12-31"):
        await calls.create(
            scene,
            value,
            run=await calls.run(scene.project.id, YEAR_2024),
            time_range=TimeRange(start=date(2020, 1, 1)),
        )
    assert await calls.reports("list", scene.project.id) == []

    await calls.create(scene, value, name="Findings")
    with pytest.raises(Invalid, match="add a version"):
        await calls.create(scene, value, name=" Findings ")
    # Another owner may use the name.
    await calls.create(scene, value, session_id=None, dashboard_id=scene.dashboard.id)


async def test_a_version_is_numbered_by_what_changed(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(heading("Gap"), shows(scene.value)))
    # The same operator in another widget is the same pipeline: only static changes.
    patch = await calls.add(first, blocks(heading("The gap"), shows(scene.table, "By region")))
    with pytest.raises(Invalid, match="Nothing changed against version 1.0.1"):
        await calls.add(patch, blocks(heading("The gap"), shows(scene.table, "By region")))
    same = blocks(heading("The gap"), shows(scene.table, "By region"))
    minor = await calls.add(patch, same, await calls.run(scene.project.id, YEAR_2024))
    major = await calls.add(minor, blocks(shows(scene.chart)))
    with pytest.raises(Invalid, match="minor version is too small"):
        await calls.add(major, blocks(shows(scene.value)), bump=VersionBump.MINOR)
    chosen = await calls.add(major, blocks(text("Reworded"), shows(scene.chart)), bump="major")

    assert [v.version for v in (first, patch, minor, major, chosen)] == [
        "1.0.0",
        "1.0.1",
        "1.1.0",
        "2.0.0",
        "3.0.0",
    ]
    assert minor.time_range == YEAR_2024
    report = await calls.reports("get", first.report_id)
    assert (report.latest_version_id, report.revision) == (chosen.id, 5)


async def test_a_version_is_announced_after_the_commit_and_a_failed_write_announces_nothing(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    with pytest.raises(Invalid):
        async with container() as request:
            service = await request.get(ReportService)
            await service.add_version(
                first.report_id,
                blocks(text("More"), shows(scene.value)),
                first.run_id,
                first.time_range,
                AGENT,
            )
            raise Invalid("the request fails after the version was written")

    events = [e for e in await published(container) if e.type is EventType.REPORT_VERSION_CREATED]
    assert [e.payload for e in events] == [
        {"report_id": str(first.report_id), "version_id": str(first.id), "version": "1.0.0"}
    ]
    assert events[0].project_id == scene.project.id


async def test_the_sources_list_names_every_source_behind_the_widgets(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    version = await calls.create(scene, blocks(shows(scene.chart), shows(scene.value)))
    run = await calls.run_of(version.run_id)
    # The widgets the version shows: its copies of the chart and the value.
    chart, value = (str(widget.id) for widget in await shown(container, version))

    assert version.content["sources"] == [
        {
            "data_source_id": str(scene.source_a.id),
            "name": "Sotkanet",
            "address": "https://sotkanet.test/3621.csv",
            "access_kind": "url",
            "format": "csv",
            "operator_id": scene.operator_a.id,
            "snapshot_id": str(run.snapshots[scene.operator_a.id]),
            "fetched_at": FETCHED_A.isoformat().replace("+00:00", "Z"),
            "content_hash": "aaa",
            "widget_ids": [chart, value],
        },
        {
            "data_source_id": str(scene.source_b.id),
            "name": "Statistics Finland",
            "address": "https://statfin.test/13u5.csv",
            "access_kind": "url",
            "format": "csv",
            "operator_id": scene.operator_b.id,
            "snapshot_id": str(run.snapshots[scene.operator_b.id]),
            "fetched_at": FETCHED_B.isoformat().replace("+00:00", "Z"),
            "content_hash": "bbb",
            "widget_ids": [chart],
        },
    ]
    # Served typed, as stored.
    sources = await calls.reports("sources", version.id)
    assert all(isinstance(source, ReportSource) for source in sources)
    assert [source.model_dump(mode="json") for source in sources] == version.content["sources"]


async def test_the_sources_list_follows_the_runs_input_bindings(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    async with container() as request:
        operators = await request.get(OperatorRepository)
        slot = await operators.add(
            factories.operator(
                scene.project.id, OperatorKind.INPUT, {"name": "regions"}, (scene.operator_a.id,)
            )
        )
        over = await operators.add(
            factories.operator(scene.project.id, params={"sql": "SELECT 2"}, inputs=(slot.id,))
        )
        widget = db_helpers.widget(scene.project.id, over.id)
        await (await request.get(WidgetRepository)).add(widget)
        scenario = await (await request.get(RunService)).start(
            scene.project.id, AGENT, bindings={"regions": scene.operator_b.id}
        )

    version = await calls.create(scene, blocks(shows(widget)), run=scenario)

    assert [source["name"] for source in version.content["sources"]] == ["Statistics Finland"]


async def test_a_dashboard_is_frozen_into_a_report_of_its_name(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    def generate(name: str = "Monthly", **kwargs: Any) -> Any:
        return calls.reports("generate_from_dashboard", scene.dashboard.id, name, AGENT, **kwargs)

    first = await generate()
    again = await generate()
    async with container() as request:
        dashboards = await request.get(DashboardService)
        dashboard = await dashboards.get(scene.dashboard.id)
        await dashboards.edit(
            dashboard.id, [Slot(name="only", widget_id=scene.value.id)], dashboard.revision, AGENT
        )
    narrowed = await generate(run_id=again.run_id)
    other = await generate("Yearly")

    # At a new run of the dashboard's range; top to bottom on the grid, the empty slot left out.
    assert (first.version, first.time_range) == ("1.0.0", YEAR_2024)
    assert first.dashboard_version_id == scene.dashboard_version.id
    value, chart = await shown(container, first)
    assert (value.copied_from, chart.copied_from) == (scene.value.id, scene.chart.id)
    assert first.content["blocks"] == [
        {"type": "widget", "widget_id": str(value.id), "caption": ""},
        {"type": "widget", "widget_id": str(chart.id), "caption": ""},
    ]
    report = await calls.reports("get", first.report_id)
    assert (report.dashboard_id, report.session_id, report.name) == (
        scene.dashboard.id,
        None,
        "Monthly",
    )
    assert (again.report_id, again.version) == (first.report_id, "1.1.0")
    # A widget fewer is a pipeline fewer.
    assert (narrowed.version, narrowed.run_id) == ("2.0.0", again.run_id)
    assert (other.report_id != first.report_id, other.version) == (True, "1.0.0")
    with pytest.raises(Invalid, match="was started for"):
        await generate("Bad", run_id=first.run_id, time_range=TimeRange(start=date(2015, 1, 1)))


async def test_a_report_template_is_filled_with_widgets(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    template = await calls.templates(
        "create",
        scene.project.id,
        "Brief",
        TemplateKind.REPORT,
        [Slot(name="gap"), Slot(name="trend", widget_id=scene.chart.id)],
        blocks(
            heading("Gap"),
            {"type": "widget", "slot": "gap", "caption": "Latest year"},
            {"type": "section", "title": "Trend", "blocks": [{"type": "widget", "slot": "trend"}]},
        ),
    )
    assert await calls.templates("list", scene.project.id) == [template]

    version = await calls.create(
        scene, {"slots": {"gap": str(scene.value.id)}}, template_id=template.id
    )
    second = await calls.add(version, {"slots": {"gap": str(scene.table.id)}})

    assert version.template_id == template.id
    value, chart = await shown(container, version)
    assert (value.copied_from, chart.copied_from) == (scene.value.id, scene.chart.id)
    assert version.content["blocks"] == [
        {"type": "heading", "text": "Gap", "level": 2},
        {"type": "widget", "widget_id": str(value.id), "caption": "Latest year"},
        {
            "type": "section",
            "title": "Trend",
            "blocks": [{"type": "widget", "widget_id": str(chart.id), "caption": ""}],
        },
    ]
    # The next version may fill the same template again; it keeps the template.
    assert (second.version, second.template_id) == ("1.0.1", template.id)
    with pytest.raises(Invalid, match=re.escape("missing: ['gap']")):
        await calls.create(scene, {"slots": {}}, template_id=template.id, name="Other")


@pytest.mark.parametrize(
    ("kind", "slots", "content", "message"),
    [
        (
            TemplateKind.REPORT,
            [Slot(name="a")],
            blocks({"type": "widget", "slot": "b"}),
            "not declared",
        ),
        (TemplateKind.DASHBOARD, [Slot(name="a", layout={"x": 8, "w": 6})], None, "12 columns"),
    ],
)
async def test_a_wrong_template_is_invalid(
    calls: Calls, scene: Scene, kind: TemplateKind, slots: list[Slot], content: Any, message: str
) -> None:
    with pytest.raises(Invalid, match=message):
        await calls.templates("create", scene.project.id, "T", kind, slots, content)


# MCP, the transport an agent writes reports through


@pytest.fixture(scope="module")
async def agent(unreachable_settings: Settings) -> AsyncIterator[tuple[Client, AsyncContainer]]:
    async with mcp_client(unreachable_settings, ReportFakes()) as (client, seen):
        yield client, seen.container


async def test_the_report_tools_are_served_and_documented(
    agent: tuple[Client, AsyncContainer],
) -> None:
    client, _ = agent
    tools = {tool.name: tool for tool in await client.list_tools()}
    assert {
        "create_report",
        "add_report_version",
        "generate_report_from_dashboard",
        "list_reports",
        "get_report",
        "create_template",
        "list_templates",
    } <= set(tools)
    # An agent learns the tree from the tools that take one.
    for name in ("create_report", "add_report_version"):
        description = tools[name].description or ""
        assert '"type": "widget", "widget_id"' in description, name
        assert "Leave out `sources`" in description, name


async def test_an_agent_writes_reads_and_versions_a_report(
    agent: tuple[Client, AsyncContainer],
) -> None:
    client, container = agent
    scene = await seed(container)
    created = await call(
        client,
        "create_report",
        project_id=str(scene.project.id),
        name="Findings",
        content=blocks(heading("Gap"), shows(scene.value)),
        session_id=str(scene.session.id),
    )
    report, version = created["report"], created["version"]

    added = await call(
        client,
        "add_report_version",
        session_id=str(scene.session.id),
        report_id=report["id"],
        content=blocks(heading("Gap"), shows(scene.value), shows(scene.chart)),
        run_id=version["run_id"],
        expected_revision=1,
    )
    first = await call(
        client,
        "get_report",
        session_id=str(scene.session.id),
        report_id=report["id"],
        version="1.0.0",
    )

    assert version["created_by"] == {"kind": "external_agent", "name": "claude-code"}
    assert created["url"] == f"/projects/{scene.project.id}/reports/{report['id']}?version=1.0.0"
    assert [s["name"] for s in version["content"]["sources"]] == ["Sotkanet"]
    assert (added["version"]["version"], added["versions"]) == ("2.0.0", ["1.0.0", "2.0.0"])
    assert first["version"]["id"] == version["id"]
    # Each new version is attached to the session in place of the one before.
    async with container() as request:
        [attached] = await (await request.get(AttachmentService)).list(scene.session.id)
    assert (attached.kind, attached.ref, attached.title) == (
        "report",
        added["version"]["id"],
        "Findings 2.0.0",
    )
    with pytest.raises(ToolError, match="revision 2, but the write expected revision 1"):
        await call(
            client,
            "add_report_version",
            session_id=str(scene.session.id),
            report_id=report["id"],
            content=blocks(shows(scene.table)),
            expected_revision=1,
        )
    with pytest.raises(ToolError, match="unknown component 'chart'"):
        await call(
            client,
            "create_report",
            project_id=str(scene.project.id),
            name="Other",
            content=blocks({"type": "chart"}),
            session_id=str(scene.session.id),
        )


# REST: the routes are wired


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides(), ReportFakes()) as client:
        yield client


def test_a_report_is_created_versioned_and_read_over_rest(client: TestClient) -> None:
    container = client.app.state.dishka_container  # type: ignore[attr-defined]
    assert client.portal is not None
    scene = client.portal.call(seed, container)
    path = f"/projects/{scene.project.id}/reports"
    body = {"name": "Findings", "content": blocks(shows(scene.value))}

    version = send(client, "POST", path, body | {"session_id": str(scene.session.id)}, 201)
    added = send(
        client,
        "POST",
        f"/reports/{version['report_id']}/versions",
        {"content": blocks(text("More"), shows(scene.value)), "expected_revision": 1},
        201,
    )
    invalid = client.post(
        f"/api{path}",
        json={"name": "Other", "content": blocks({"type": "chart"}), "session_id": None},
    )

    assert version["created_by"] == {"kind": "user", "name": "web"}
    # No run named: one was started, with an open range; so is the next version's.
    assert added["version"] == "1.1.0"
    assert (
        send(client, "GET", f"/reports/{version['report_id']}")["latest_version_id"]
        == (added["id"])
    )
    sources = send(client, "GET", f"/report-versions/{version['id']}/sources")
    assert [source["name"] for source in sources] == ["Sotkanet"]
    assert invalid.status_code == 422
    assert client.get(f"/api/reports/{uuid7()}").status_code == 404


# PostgreSQL


async def test_two_versions_at_once_conflict_on_postgresql(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = settings_in(tmp_path, migrated_database_url)
    container = create_container(
        settings, FastapiProvider(), MemoryBackground(), Overrides(), ReportFakes()
    )
    try:
        scene = await seed(container)
        async with container() as request:
            first = await (await request.get(ReportService)).generate_from_dashboard(
                scene.dashboard.id, "Monthly", AGENT
            )

        async def add(words: str) -> ReportVersion:
            async with container() as request:
                return await (await request.get(ReportService)).add_version(
                    first.report_id,
                    blocks(text(words), shows(scene.value), shows(scene.chart)),
                    first.run_id,
                    first.time_range,
                    AGENT,
                )

        outcomes = await asyncio.gather(add("Mine"), add("Theirs"), return_exceptions=True)
        async with container() as request:
            reports = await request.get(ReportService)
            versions = await reports.versions(first.report_id)
            stored = await reports.version(first.id)
    finally:
        await container.close()

    assert sorted(type(o).__name__ for o in outcomes) == ["Conflict", "ReportVersion"]
    assert [v.version for v in versions] == ["1.0.0", "1.0.1"]
    # The tree and the dashboard version come back as they went in.
    assert stored == first
    assert stored.dashboard_version_id == scene.dashboard_version.id
    assert isinstance(next(o for o in outcomes if not isinstance(o, ReportVersion)), Conflict)
