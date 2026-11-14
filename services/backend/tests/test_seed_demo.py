import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from dishka import Provider, Scope

from ada.adapters.clock import SystemClock
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.sources.examples import EXAMPLES, NORDCAN_LUNG_SURVIVAL, STATFIN_CANCER_DEATHS
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState
from ada.core.ports.sources import SourceReaders
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.reports import ReportService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.seed import DEMO_DASHBOARD, DEMO_PROJECT, DEMO_RANGE, seed_demo
from memory import MemoryBackground
from test_sources_examples import RECORDINGS, Replay

pytestmark = pytest.mark.anyio


class Sotkanet2022To2024:
    """The recorded answers, plus Sotkanet's answer for 2022-2024, which is the recorded
    2022 answer and the recorded 2023-2024 one together: the demo's range in one request."""

    def __init__(self) -> None:
        self.replay = Replay()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/rest/1.1/json" and request.url.params.get_list("years") == [
            "2022",
            "2023",
            "2024",
        ]:
            rows = [
                *json.loads((RECORDINGS / "sotkanet-3621-2022.json").read_bytes()),
                *json.loads((RECORDINGS / "sotkanet-3621.json").read_bytes()),
            ]
            return httpx.Response(200, json=rows)
        return self.replay(request)


async def test_seeding_builds_the_demo_once_and_fetches_its_data(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    outside = Sotkanet2022To2024()
    readers = Provider(scope=Scope.APP)
    readers.provide(
        lambda: HttpSourceReaders(create_client(httpx.MockTransport(outside)), SystemClock()),
        provides=SourceReaders,
    )
    container = create_container(settings, MemoryBackground(), readers)
    try:
        # Without --refresh the demo is built from the declared schemas: nothing is fetched.
        project_id = await seed_demo(container)
        assert outside.requests == []
        # Fetching then fills it, with a handful of requests to the public APIs.
        assert await seed_demo(container, refresh=True) == project_id
        assert len(outside.requests) <= 8
        hosts = {request.url.host for request in outside.requests}
        assert hosts == {"sotkanet.fi", "geo.stat.fi", "canapi.iarc.who.int"}
        # Seeding again adds nothing, and fetches nothing that is fresh.
        fetched = len(outside.requests)
        assert await seed_demo(container, refresh=True) == project_id
        assert len(outside.requests) == fetched

        async with container() as request:
            projects = await (await request.get(ProjectService)).list()
            sources = await (await request.get(SourceService)).list(project_id)
            dashboards = await (await request.get(DashboardService)).list(project_id)
            widgets = await (await request.get(WidgetService)).list(project_id)
            sessions = await (await request.get(SessionService)).list(project_id)
            reports = await (await request.get(ReportService)).list(project_id)
            alerts = await request.get(AlertService)
            rules = await alerts.list_rules(dashboards[0].id)
            firing = await alerts.alerts(project_id, AlertState.FIRING)
            current = await (await request.get(DashboardService)).current(dashboards[0].id)
            versions = await (await request.get(ReportService)).versions(reports[0].id)
        assert [project.name for project in projects] == [DEMO_PROJECT]
        assert [source.name for source in sources] == [example.name for example in EXAMPLES]
        assert [(d.name, d.default_time_range) for d in dashboards] == [
            (DEMO_DASHBOARD, DEMO_RANGE)
        ]
        assert current is not None and [slot.name for slot in current.slots] == [
            "Map",
            "By county",
        ]
        assert sorted(widget.type for widget in widgets) == ["line-chart", "map", "table"]
        assert len(sessions) == 1 and sessions[0].panel_dashboard_id == dashboards[0].id
        assert len(rules) == 1
        # East Uusimaa, West Uusimaa, Vantaa and Kerava, and Helsinki are below 80 % in 2024.
        assert sorted(alert.key["county_code"] for alert in firing) == ["01", "03", "04", "90"]
        assert [version.version for version in versions] == ["1.0.0"]

        # The source the demo does not show is left to the worker.
        dispatcher = await container.get(TaskDispatcher)
        assert isinstance(dispatcher, RecordingTaskDispatcher)
        statfin = next(s for s in sources if s.name == STATFIN_CANCER_DEATHS.name)
        assert dispatcher.refreshes == [(statfin.id, True), (statfin.id, True)]
    finally:
        await container.close()


async def test_seeding_registers_anew_what_an_older_seed_registered_differently(
    migrated_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=migrated_database_url, valkey_url="redis://127.0.0.1:1/0", data_dir=tmp_path
    )
    container = create_container(settings, MemoryBackground())
    try:
        async with container() as request:
            project = await (await request.get(ProjectService)).create(DEMO_PROJECT)
            # As wave 1 registered it: the period as text only, no period columns.
            older = NORDCAN_LUNG_SURVIVAL.model_copy(update={"declared_schema": None})
            old = await (await request.get(SourceService)).register(
                project.id, **older.registration()
            )
        assert await seed_demo(container) == project.id
        async with container() as request:
            sources = await (await request.get(SourceService)).list(project.id)
        names = {source.name: source for source in sources}
        assert names[NORDCAN_LUNG_SURVIVAL.name].id != old.id
        assert [s.name for s in sources if s.id == old.id] == [
            f"{NORDCAN_LUNG_SURVIVAL.name} (before {date.today()})"
        ]
    finally:
        await container.close()
