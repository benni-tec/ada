"""Reports against PostgreSQL: the services on the SQL repositories, through the container
as a request uses them. Needs `moon run root:infra` (skipped locally without it)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider

import factories
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.dashboards import Slot
from ada.core.models.errors import Conflict
from ada.core.models.events import EventType
from ada.core.models.reports import ReportVersion, TemplateKind
from ada.core.models.time import TimeRange
from ada.core.services.ports.reports import ReportService, TemplateService
from ada.core.services.ports.runs import RunService
from memory import MemoryBackground
from test_api_support import Overrides
from test_reports_support import (
    FETCHED_A,
    YEAR_2024,
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
async def container(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[AsyncContainer]:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    container = create_container(
        settings, FastapiProvider(), MemoryBackground(), Overrides(), ReportFakes()
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def scene(container: AsyncContainer) -> Scene:
    return await seed(container)


async def create(container: AsyncContainer, scene: Scene, content: dict) -> ReportVersion:
    async with container() as request:
        run = await (await request.get(RunService)).start(scene.project.id, AGENT, YEAR_2024)
        return await (await request.get(ReportService)).create(
            scene.project.id,
            "Findings",
            content,
            run.id,
            run.time_range,
            AGENT,
            session_id=scene.session.id,
        )


async def test_versions_and_their_trees_round_trip(container: AsyncContainer, scene: Scene) -> None:
    first = await create(container, scene, blocks(heading("Gap"), shows(scene.chart)))
    async with container() as request:
        reports = await request.get(ReportService)
        second = await reports.add_version(
            first.report_id,
            blocks(heading("The gap"), shows(scene.chart, "Both sources")),
            first.run_id,
            first.time_range,
            AGENT,
        )
    async with container() as request:
        reports = await request.get(ReportService)
        assert await reports.versions(first.report_id) == [first, second]
        stored = await reports.version(second.id)
        report = await reports.get(first.report_id)
    assert stored.version == "1.0.1"
    assert stored.time_range == YEAR_2024
    assert stored.content["blocks"][1]["caption"] == "Both sources"
    [sotkanet, _] = stored.content["sources"]
    assert sotkanet["fetched_at"] == FETCHED_A.isoformat().replace("+00:00", "Z")
    assert report.latest_version_id == second.id
    assert report.revision == 2
    events = [e for e in await published(container) if e.type is EventType.REPORT_VERSION_CREATED]
    assert [e.payload["version"] for e in events] == ["1.0.0", "1.0.1"]


async def test_two_versions_at_once_conflict(container: AsyncContainer, scene: Scene) -> None:
    first = await create(container, scene, blocks(shows(scene.value)))

    async def add(words: str) -> ReportVersion:
        async with container() as request:
            return await (await request.get(ReportService)).add_version(
                first.report_id,
                blocks(text(words), shows(scene.value)),
                first.run_id,
                first.time_range,
                AGENT,
            )

    outcomes = await asyncio.gather(add("Mine"), add("Theirs"), return_exceptions=True)
    added = [o for o in outcomes if isinstance(o, ReportVersion)]
    assert len(added) == 1
    assert added[0].version == "1.0.1"
    assert len([o for o in outcomes if isinstance(o, Conflict)]) == 1
    async with container() as request:
        versions = await (await request.get(ReportService)).versions(first.report_id)
    assert [v.version for v in versions] == ["1.0.0", "1.0.1"]


async def test_a_generated_report_records_its_dashboard_version(
    container: AsyncContainer, scene: Scene
) -> None:
    async with container() as request:
        version = await (await request.get(ReportService)).generate_from_dashboard(
            scene.dashboard.id, "Monthly", AGENT
        )
    async with container() as request:
        reports = await request.get(ReportService)
        stored = await reports.version(version.id)
        [report] = await reports.list(scene.project.id)
    assert stored.dashboard_version_id == scene.dashboard_version.id
    assert report.dashboard_id == scene.dashboard.id
    assert stored.time_range == YEAR_2024


async def test_templates_round_trip(container: AsyncContainer, scene: Scene) -> None:
    async with container() as request:
        template = await (await request.get(TemplateService)).create(
            scene.project.id,
            "Brief",
            TemplateKind.REPORT,
            [Slot(name="gap", description="Headline", widget_id=scene.value.id)],
            blocks(heading("Gap"), {"type": "widget", "slot": "gap"}),
        )
    async with container() as request:
        templates = await request.get(TemplateService)
        assert await templates.get(template.id) == template
        assert await templates.list(scene.project.id) == [template]
    async with container() as request:
        run = await (await request.get(RunService)).start(scene.project.id, AGENT)
        version = await (await request.get(ReportService)).create(
            scene.project.id,
            "Brief 2024",
            {"slots": {}},
            run.id,
            TimeRange(),
            AGENT,
            session_id=scene.session.id,
            template_id=template.id,
        )
    assert version.template_id == template.id
    assert version.content["blocks"][1]["widget_id"] == str(scene.value.id)
