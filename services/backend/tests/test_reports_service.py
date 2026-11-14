"""ReportService and TemplateService on the memory repositories, with fake runs and a fake
dashboard service."""

from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID, uuid7

import pytest
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider

import db_helpers
import factories
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Invalid
from ada.core.models.events import EventType
from ada.core.models.operators import Operator, OperatorKind
from ada.core.models.reports import ReportSource, ReportVersion, TemplateKind, VersionBump
from ada.core.models.runs import Run
from ada.core.models.time import TimeRange
from ada.core.ports.repositories import OperatorRepository, SessionRepository, WidgetRepository
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.ports.runs import RunService
from memory import memory_adapters
from test_api_support import Overrides
from test_reports_support import (
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
            run.time_range,
            AGENT,
            **kwargs,
        )

    async def add(
        self, version: ReportVersion, content: dict[str, Any], run: Run | None = None, **kwargs: Any
    ) -> ReportVersion:
        report = await self.reports("get", version.report_id)
        if run is None:
            run = await self.run_of(version.run_id)
        return await self.reports(
            "add_version", report.id, content, run.id, run.time_range, AGENT, **kwargs
        )

    async def run_of(self, run_id: UUID) -> Run:
        async with self.container() as request:
            return await (await request.get(RunService)).get(run_id)


@pytest.fixture
def calls(container: AsyncContainer) -> Calls:
    return Calls(container)


# Creating a report


async def test_a_report_starts_at_version_1_0_0(calls: Calls, scene: Scene) -> None:
    run = await calls.run(scene.project.id, YEAR_2024)
    version = await calls.create(scene, blocks(heading("Gap"), shows(scene.value)), run=run)

    assert version.version == "1.0.0"
    assert version.run_id == run.id
    assert version.time_range == YEAR_2024
    assert version.created_by == AGENT
    assert version.content["blocks"] == [
        {"type": "heading", "text": "Gap", "level": 2},
        {"type": "widget", "widget_id": str(scene.value.id), "caption": ""},
    ]
    report = await calls.reports("get", version.report_id)
    assert report.name == "Findings"
    assert report.session_id == scene.session.id
    assert report.dashboard_id is None
    assert report.latest_version_id == version.id
    assert report.revision == 1
    assert await calls.reports("list", scene.project.id) == [report]
    assert await calls.reports("versions", report.id) == [version]
    assert await calls.reports("version", version.id) == version


async def test_freezing_executes_each_widget_operator_once_in_the_run(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    run = await calls.run(scene.project.id)
    await calls.create(
        scene, blocks(shows(scene.value), shows(scene.table), shows(scene.chart)), run=run
    )
    executed = (await container.get(Executed)).calls
    assert executed == [(run.id, scene.cleaned.id), (run.id, scene.joined.id)]
    pinned = await calls.run_of(run.id)
    assert set(pinned.snapshots) == {scene.operator_a.id, scene.operator_b.id}


@pytest.mark.parametrize(
    "owner",
    [{}, {"session_id": "session", "dashboard_id": "dashboard"}],
    ids=["no owner", "two owners"],
)
async def test_a_report_has_exactly_one_owner(
    calls: Calls, scene: Scene, owner: dict[str, str]
) -> None:
    ids = {"session": scene.session.id, "dashboard": scene.dashboard.id}
    kwargs = {key: ids[value] for key, value in owner.items()}
    kwargs.setdefault("session_id", None)
    with pytest.raises(Invalid, match="exactly one session or one dashboard"):
        await calls.create(scene, blocks(shows(scene.value)), **kwargs)


async def test_a_report_shows_only_widgets_of_its_project(calls: Calls, scene: Scene) -> None:
    with pytest.raises(Invalid, match="another project"):
        await calls.create(scene, blocks(shows(scene.stranger)))
    with pytest.raises(Invalid, match="does not exist"):
        await calls.create(scene, blocks(shows(uuid7())))
    assert await calls.reports("list", scene.project.id) == []


async def test_an_invalid_tree_is_rejected(calls: Calls, scene: Scene) -> None:
    with pytest.raises(Invalid, match="unknown component 'chart'"):
        await calls.create(scene, blocks({"type": "chart", "rows": [[1]]}))
    with pytest.raises(Invalid, match="at least one block"):
        await calls.create(scene, blocks())


async def test_the_run_must_be_of_the_project_and_match_the_range(
    calls: Calls, scene: Scene
) -> None:
    foreign = await calls.run(scene.other_project.id)
    with pytest.raises(Invalid, match="another project"):
        await calls.create(scene, blocks(shows(scene.value)), run=foreign)
    run = await calls.run(scene.project.id, YEAR_2024)
    with pytest.raises(Invalid, match="was started for 2024-01-01 to 2024-12-31"):
        await calls.reports(
            "create",
            scene.project.id,
            "Findings",
            blocks(shows(scene.value)),
            run.id,
            TimeRange(start=date(2020, 1, 1)),
            AGENT,
            session_id=scene.session.id,
        )


async def test_an_owner_has_one_report_of_a_name(calls: Calls, scene: Scene) -> None:
    await calls.create(scene, blocks(shows(scene.value)), name="Findings")
    with pytest.raises(Invalid, match="add a version"):
        await calls.create(scene, blocks(shows(scene.table)), name=" Findings ")
    # Another owner may use the name.
    await calls.create(
        scene,
        blocks(shows(scene.value)),
        name="Findings",
        session_id=None,
        dashboard_id=scene.dashboard.id,
    )


async def test_a_session_of_another_project_cannot_own_a_report(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    foreign = factories.session(scene.other_project.id)
    async with container() as request:
        await (await request.get(SessionRepository)).add(foreign)
    with pytest.raises(Invalid, match="session belongs to another project"):
        await calls.create(scene, blocks(shows(scene.value)), session_id=foreign.id)


# Versions


async def test_only_static_changes_make_a_patch(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(heading("Gap"), shows(scene.value)))
    second = await calls.add(first, blocks(heading("The gap"), shows(scene.value)))
    assert second.version == "1.0.1"
    assert second.run_id == first.run_id
    # The same operator in another widget is the same pipeline: still comparable.
    third = await calls.add(second, blocks(heading("The gap"), shows(scene.table, "By region")))
    assert third.version == "1.0.2"


async def test_a_new_run_or_range_makes_a_minor_version(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    refreshed = await calls.add(
        first, blocks(shows(scene.value)), await calls.run(scene.project.id)
    )
    assert refreshed.version == "1.1.0"
    ranged = await calls.add(
        refreshed, blocks(shows(scene.value)), await calls.run(scene.project.id, YEAR_2024)
    )
    assert ranged.version == "1.2.0"
    assert ranged.time_range == YEAR_2024


async def test_changed_pipelines_make_a_major_version(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    added = await calls.add(first, blocks(shows(scene.value), shows(scene.chart)))
    assert added.version == "2.0.0"
    removed = await calls.add(added, blocks(shows(scene.chart)), await calls.run(scene.project.id))
    assert removed.version == "3.0.0"


async def test_a_version_that_changes_nothing_is_refused(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    with pytest.raises(Invalid, match="Nothing changed against version 1.0.0"):
        await calls.add(first, blocks(shows(scene.value)))


async def test_a_given_level_is_checked(calls: Calls, scene: Scene) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    with pytest.raises(Invalid, match="patch version is too small"):
        await calls.add(
            first,
            blocks(shows(scene.value)),
            await calls.run(scene.project.id),
            bump=VersionBump.PATCH,
        )
    with pytest.raises(Invalid, match="minor version is too small"):
        await calls.add(first, blocks(shows(scene.chart)), bump=VersionBump.MINOR)
    # Higher than needed is the author's call, e.g. a definition the platform cannot see.
    major = await calls.add(first, blocks(text("Reworded"), shows(scene.value)), bump="major")
    assert major.version == "2.0.0"


async def test_versions_are_listed_by_number(calls: Calls, scene: Scene) -> None:
    version = await calls.create(scene, blocks(shows(scene.value)))
    for _ in range(10):
        version = await calls.add(
            version, blocks(shows(scene.value)), await calls.run(scene.project.id)
        )
    numbers = [v.version for v in await calls.reports("versions", version.report_id)]
    assert numbers[-3:] == ["1.8.0", "1.9.0", "1.10.0"]
    report = await calls.reports("get", version.report_id)
    assert report.latest_version_id == version.id
    assert report.revision == 11


async def test_a_new_version_is_announced_after_the_commit(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    first = await calls.create(scene, blocks(shows(scene.value)))
    second = await calls.add(first, blocks(text("More"), shows(scene.value)))
    events = [e for e in await published(container) if e.type is EventType.REPORT_VERSION_CREATED]
    assert [e.payload for e in events] == [
        {"report_id": str(first.report_id), "version_id": str(first.id), "version": "1.0.0"},
        {"report_id": str(first.report_id), "version_id": str(second.id), "version": "1.0.1"},
    ]
    assert all(e.project_id == scene.project.id for e in events)


async def test_a_failed_write_announces_nothing(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    with pytest.raises(Invalid):
        async with container() as request:
            service = await request.get(ReportService)
            run = await (await request.get(RunService)).start(scene.project.id, AGENT)
            await service.create(
                scene.project.id,
                "Findings",
                blocks(shows(scene.value)),
                run.id,
                run.time_range,
                AGENT,
                session_id=scene.session.id,
            )
            raise Invalid("the request fails after the report was written")
    assert not [e for e in await published(container) if e.type is EventType.REPORT_VERSION_CREATED]


# The sources list


async def test_the_sources_list_names_every_source_behind_the_widgets(
    calls: Calls, scene: Scene
) -> None:
    version = await calls.create(
        scene, blocks(shows(scene.chart), shows(scene.value), shows(scene.table))
    )
    run = await calls.run_of(version.run_id)
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
            "widget_ids": [str(scene.chart.id), str(scene.value.id), str(scene.table.id)],
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
            "widget_ids": [str(scene.chart.id)],
        },
    ]


async def test_the_service_serves_the_stored_sources_list_typed(calls: Calls, scene: Scene) -> None:
    version = await calls.create(scene, blocks(shows(scene.chart)))
    sources = await calls.reports("sources", version.id)
    assert all(isinstance(source, ReportSource) for source in sources)
    assert [source.name for source in sources] == ["Sotkanet", "Statistics Finland"]
    assert sources[0].fetched_at == FETCHED_A
    assert sources[0].widget_ids == (scene.chart.id,)
    # As stored: a later edit of the source does not change what the version rests on.
    assert [source.model_dump(mode="json") for source in sources] == version.content["sources"]


async def test_the_sources_list_follows_the_runs_input_bindings(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    async with container() as request:
        operators = await request.get(OperatorRepository)
        widgets = await request.get(WidgetRepository)
        slot: Operator = await operators.add(
            factories.operator(
                scene.project.id, OperatorKind.INPUT, {"name": "regions"}, (scene.operator_a.id,)
            )
        )
        over = await operators.add(
            factories.operator(scene.project.id, params={"sql": "SELECT 2"}, inputs=(slot.id,))
        )
        widget = db_helpers.widget(scene.project.id, over.id)
        await widgets.add(widget)
        scenario = await (await request.get(RunService)).start(
            scene.project.id, AGENT, bindings={"regions": scene.operator_b.id}
        )
    version = await calls.create(scene, blocks(shows(widget)), run=scenario)
    assert [source["name"] for source in version.content["sources"]] == ["Statistics Finland"]


async def test_the_sources_list_cannot_be_written(calls: Calls, scene: Scene) -> None:
    with pytest.raises(Invalid, match="`sources` is generated"):
        await calls.create(scene, {"blocks": [shows(scene.value)], "sources": []})


# Generating from a dashboard


async def test_a_dashboard_is_frozen_at_a_new_run_of_its_default_range(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    version = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT)

    assert version.version == "1.0.0"
    assert version.dashboard_version_id == scene.dashboard_version.id
    assert version.time_range == YEAR_2024
    run = await calls.run_of(version.run_id)
    assert run.time_range == YEAR_2024
    assert run.started_by == AGENT
    # Top to bottom on the grid; the empty slot is left out.
    assert version.content["blocks"] == [
        {"type": "widget", "widget_id": str(scene.value.id), "caption": ""},
        {"type": "widget", "widget_id": str(scene.chart.id), "caption": ""},
    ]
    assert {s["name"] for s in version.content["sources"]} == {"Sotkanet", "Statistics Finland"}
    report = await calls.reports("get", version.report_id)
    assert report.dashboard_id == scene.dashboard.id
    assert report.session_id is None
    assert report.name == "Monthly"


async def test_generating_again_adds_a_version_to_the_report_of_that_name(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    first = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT)
    second = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT)
    assert second.report_id == first.report_id
    assert second.version == "1.1.0"
    assert second.run_id != first.run_id

    async with container() as request:
        dashboards = await request.get(DashboardService)
        dashboard = await dashboards.get(scene.dashboard.id)
        edited = await dashboards.pin_widget(
            dashboard.id, scene.table.id, "detail", dashboard.revision, AGENT
        )
    # The table reads the same operator as the value widget: the pipelines did not change.
    third = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT)
    assert third.version == "1.2.0"
    assert third.dashboard_version_id == edited.id

    other = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Yearly", AGENT)
    assert other.report_id != first.report_id
    assert other.version == "1.0.0"


async def test_a_dashboard_with_new_pipelines_makes_a_major_version(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    first = await calls.reports("generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT)
    async with container() as request:
        dashboards = await request.get(DashboardService)
        dashboard = await dashboards.get(scene.dashboard.id)
        await dashboards.edit(
            dashboard.id, [Slot(name="only", widget_id=scene.value.id)], dashboard.revision, AGENT
        )
    second = await calls.reports(
        "generate_from_dashboard", scene.dashboard.id, "Monthly", AGENT, run_id=first.run_id
    )
    assert second.version == "2.0.0"
    assert second.run_id == first.run_id


async def test_a_dashboard_is_frozen_at_a_given_run_or_range(calls: Calls, scene: Scene) -> None:
    run = await calls.run(scene.project.id)
    at_run = await calls.reports(
        "generate_from_dashboard", scene.dashboard.id, "At run", AGENT, run_id=run.id
    )
    assert at_run.run_id == run.id
    assert at_run.time_range == TimeRange()

    ranged = TimeRange(start=date(2015, 1, 1), end=date(2024, 12, 31))
    in_range = await calls.reports(
        "generate_from_dashboard", scene.dashboard.id, "In range", AGENT, time_range=ranged
    )
    assert in_range.time_range == ranged
    assert (await calls.run_of(in_range.run_id)).time_range == ranged

    with pytest.raises(Invalid, match="was started for"):
        await calls.reports(
            "generate_from_dashboard",
            scene.dashboard.id,
            "Bad",
            AGENT,
            run_id=run.id,
            time_range=ranged,
        )


async def test_a_dashboard_without_widgets_cannot_be_reported(
    calls: Calls, scene: Scene, container: AsyncContainer
) -> None:
    async with container() as request:
        empty = await (await request.get(DashboardService)).create(scene.project.id, "Empty", AGENT)
    with pytest.raises(Invalid, match="shows no widgets"):
        await calls.reports("generate_from_dashboard", empty.id, "Nothing", AGENT)


# Templates


async def test_a_report_template_keeps_its_tree_and_slots(calls: Calls, scene: Scene) -> None:
    template = await calls.templates(
        "create",
        scene.project.id,
        "Brief",
        TemplateKind.REPORT,
        [Slot(name="gap", description="The headline gap"), Slot(name="trend")],
        blocks(
            heading("Gap", 1),
            {"type": "widget", "slot": "gap"},
            {"type": "widget", "slot": "trend"},
        ),
    )
    assert template.content["blocks"][1] == {"type": "widget", "slot": "gap", "caption": ""}
    assert await calls.templates("get", template.id) == template
    assert await calls.templates("list", scene.project.id) == [template]


async def test_without_a_tree_the_slots_make_one(calls: Calls, scene: Scene) -> None:
    template = await calls.templates(
        "create", scene.project.id, "Plain", TemplateKind.REPORT, [Slot(name="a"), Slot(name="b")]
    )
    assert template.content == {
        "blocks": [
            {"type": "widget", "slot": "a", "caption": ""},
            {"type": "widget", "slot": "b", "caption": ""},
        ]
    }


SLOT_A = {"type": "widget", "slot": "a"}
SLOT_B = {"type": "widget", "slot": "b"}


@pytest.mark.parametrize(
    ("kind", "slots", "content", "message"),
    [
        (TemplateKind.REPORT, [Slot(name="a")], blocks(SLOT_B), "not declared"),
        (
            TemplateKind.REPORT,
            [Slot(name="a"), Slot(name="b")],
            blocks(SLOT_A),
            "not placed: ['b']",
        ),
        (TemplateKind.REPORT, [Slot(name="a"), Slot(name="a")], None, "unique"),
        (TemplateKind.REPORT, [], None, "at least one slot"),
        (TemplateKind.REPORT, [Slot(name=" ")], None, "non-blank"),
        (TemplateKind.DASHBOARD, [Slot(name="a")], blocks(text("x")), "no content tree"),
        (TemplateKind.DASHBOARD, [Slot(name="a", layout={"x": 8, "w": 6})], None, "12 columns"),
        (TemplateKind.DASHBOARD, [Slot(name="a", layout={"x": -1})], None, "whole numbers"),
        (TemplateKind.DASHBOARD, [Slot(name="a", layout={"z": 1})], None, "unknown keys"),
    ],
)
async def test_a_wrong_template_is_invalid(
    calls: Calls, scene: Scene, kind: TemplateKind, slots: list[Slot], content: Any, message: str
) -> None:
    with pytest.raises(Invalid, match=message.replace("[", r"\[").replace("]", r"\]")):
        await calls.templates("create", scene.project.id, "T", kind, slots, content)


async def test_a_slots_default_widget_must_be_of_the_project(calls: Calls, scene: Scene) -> None:
    with pytest.raises(Invalid, match="another project"):
        await calls.templates(
            "create",
            scene.project.id,
            "T",
            TemplateKind.REPORT,
            [Slot(name="a", widget_id=scene.stranger.id)],
        )


async def test_a_dashboard_template_has_slots_on_the_grid(calls: Calls, scene: Scene) -> None:
    template = await calls.templates(
        "create",
        scene.project.id,
        "Overview",
        TemplateKind.DASHBOARD,
        [Slot(name="top", layout={"x": 0, "y": 0, "w": 12, "h": 2})],
    )
    assert template.content == {}


async def test_a_report_template_is_filled_with_widgets(calls: Calls, scene: Scene) -> None:
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
    version = await calls.create(
        scene, {"slots": {"gap": str(scene.value.id)}}, template_id=template.id
    )
    assert version.template_id == template.id
    assert version.content["blocks"] == [
        {"type": "heading", "text": "Gap", "level": 2},
        {"type": "widget", "widget_id": str(scene.value.id), "caption": "Latest year"},
        {
            "type": "section",
            "title": "Trend",
            "blocks": [{"type": "widget", "widget_id": str(scene.chart.id), "caption": ""}],
        },
    ]
    # The next version may fill the same template again; it keeps the template.
    second = await calls.add(version, {"slots": {"gap": str(scene.table.id)}})
    assert second.version == "1.0.1"
    assert second.template_id == template.id


@pytest.mark.parametrize(
    ("fill", "message"),
    [
        ({}, "missing: \\['gap'\\]"),
        ({"gap": "x", "other": "y"}, "no slots \\['other'\\]"),
        ({"gap": "not-an-id"}, "not a widget id"),
        ("gap", "maps each slot name"),
    ],
)
async def test_a_wrong_fill_is_invalid(calls: Calls, scene: Scene, fill: Any, message: str) -> None:
    template = await calls.templates(
        "create", scene.project.id, "Brief", TemplateKind.REPORT, [Slot(name="gap")]
    )
    with pytest.raises(Invalid, match=message):
        await calls.create(scene, {"slots": fill}, template_id=template.id)


async def test_only_a_report_template_of_the_project_is_filled(calls: Calls, scene: Scene) -> None:
    dashboard_template = await calls.templates(
        "create", scene.project.id, "Grid", TemplateKind.DASHBOARD, [Slot(name="gap")]
    )
    fill = {"slots": {"gap": str(scene.value.id)}}
    with pytest.raises(Invalid, match="is a dashboard template"):
        await calls.create(scene, fill, template_id=dashboard_template.id)
    with pytest.raises(Invalid, match="name the template"):
        await calls.create(scene, fill)
