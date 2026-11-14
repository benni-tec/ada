"""The slices of waves 1 and 2, driven the way an external agent drives them: over MCP;
and `ada seed-demo`, which builds the demo the same services serve.

Everything is real except the outside world: PostgreSQL (migrated), the DuckDB store on
Parquet files in tmp_path, the HTTP source readers (answering from the recorded responses
of NORDCAN, Sotkanet and Statistics Finland), and the worker's tasks, which run in an
in-memory taskiq broker with their own container, as a worker process would. Valkey is
replaced by the in-memory bus, through a broadcaster that checks, for every event, that
what it names is already committed.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope
from dishka.integrations.fastapi import FastapiProvider
from fastmcp import Client
from mcp.types import Implementation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from taskiq import InMemoryBroker

from ada.adapters.clock import SystemClock
from ada.adapters.memory.events import MemoryEventBus
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.sources.examples import (
    EXAMPLES,
    NORDCAN_LUNG_SURVIVAL,
    SOTKANET_BREAST_SCREENING,
    SOTKANET_REGIONS,
    STATFIN_CANCER_DEATHS,
    WELLBEING_COUNTY_BOUNDARIES,
)
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.adapters.valkey.tasks import ValkeyTaskDispatcher
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import AlertState
from ada.core.models.events import Event, EventType
from ada.core.models.time import TimeRange
from ada.core.ports.events import EventBroadcaster
from ada.core.ports.sources import SourceReaders
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.reports import ReportService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.seed import DEMO_DASHBOARD, DEMO_PROJECT, DEMO_RANGE, seed_demo
from ada.entrypoints.mcp.server import create_mcp
from ada.entrypoints.worker import create_broker
from fakes import RECORDINGS, Replay
from memory import MemoryBackground

pytestmark = pytest.mark.anyio

AGENT = "e2e-agent"

# Which table holds the record each payload id names.
COMMITTED = {
    "session_id": "sessions",
    "entry_id": "session_entries",
    "widget_id": "widgets",
    "run_id": "runs",
    "data_source_id": "data_sources",
    "dashboard_id": "dashboards",
    "report_id": "reports",
    "alert_id": "alerts",
    "rule_id": "alert_rules",
}


class CommittedBroadcaster:
    """Records every broadcast event, and whether each id in its payload could be read
    from another connection at that moment, i.e. had been committed."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.bus = MemoryEventBus()
        self.unseen: list[tuple[str, str]] = []

    async def publish(self, event: Event) -> None:
        async with self.engine.connect() as connection:
            for key, table in COMMITTED.items():
                if key in event.payload:
                    found = await connection.execute(
                        text(f"SELECT count(*) FROM {table} WHERE id = :id"),
                        {"id": UUID(str(event.payload[key]))},
                    )
                    if found.scalar_one() != 1:
                        self.unseen.append((event.type.value, key))
        await self.bus.publish(event)

    @property
    def types(self) -> list[EventType]:
        return [event.type for event in self.bus.published]


@dataclass
class Outside:
    """The public APIs: the recorded answers, each optionally changed by `edit`, which
    stands for the source publishing something else later."""

    replay: Replay
    edit: Callable[[httpx.Request, httpx.Response], httpx.Response] | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.replay(request)
        return self.edit(request, response) if self.edit else response


@dataclass
class Stack:
    mcp: Client
    api: AsyncContainer
    broker: InMemoryBroker
    events: CommittedBroadcaster
    replay: Replay
    outside: Outside

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self.mcp.call_tool(tool, arguments)
        content = result.structured_content
        assert content is not None
        return content["result"] if set(content) == {"result"} else content


@pytest.fixture
async def stack(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[Stack]:
    settings = Settings(
        database_url=migrated_database_url,
        valkey_url="redis://127.0.0.1:1/0",
        data_dir=tmp_path / "data",
    )
    engine = create_async_engine(migrated_database_url)
    events = CommittedBroadcaster(engine)
    replay = Replay()
    world = Outside(replay)
    readers = HttpSourceReaders(
        create_client(httpx.MockTransport(world)), SystemClock(), allow_private=True
    )

    outside = Provider(scope=Scope.APP)
    outside.provide(lambda: events, provides=EventBroadcaster)
    outside.provide(lambda: readers, provides=SourceReaders)

    # The worker: its own container, as in its own process.
    broker = create_broker(settings, MemoryBackground(), outside, in_memory=True)
    assert isinstance(broker, InMemoryBroker)
    await broker.startup()
    # The API side queues onto that broker by task name, as it queues onto Valkey.
    queue = Provider(scope=Scope.APP)
    queue.provide(lambda: ValkeyTaskDispatcher(broker), provides=TaskDispatcher)
    api = create_container(settings, FastapiProvider(), MemoryBackground(), outside, queue)
    info = Implementation(name=AGENT, version="1.0")
    try:
        async with Client(create_mcp(api, settings.widgets_dir), client_info=info) as mcp:
            yield Stack(mcp, api, broker, events, replay, world)
    finally:
        await api.close()
        await broker.shutdown()
        await engine.dispose()


async def test_an_agent_builds_a_widget_from_a_public_source(stack: Stack) -> None:
    project = await stack.call("create_project", name="Nordic cancer care")
    source = await stack.call(
        "register_source",
        project_id=project["id"],
        **NORDCAN_LUNG_SURVIVAL.model_dump(mode="json"),
    )
    session = await stack.call(
        "create_session", project_id=project["id"], title="Lung cancer survival"
    )

    # Refreshing is queued; the worker fetches the source and stores its snapshot.
    queued = await stack.call("refresh_source", source_id=source["id"])
    assert queued["status"] == "queued"
    await stack.broker.wait_all()
    [refreshed] = await stack.call("list_sources", project_id=project["id"])
    assert refreshed["last_error"] is None
    assert refreshed["last_checked_at"] is not None
    assert [request.url.host for request in stack.replay.requests] == ["canapi.iarc.who.int"]

    source_operator = await stack.call(
        "add_source_operator",
        project_id=project["id"],
        data_source_id=source["id"],
        session_id=session["id"],
        note="Survival by country, sex and period",
    )
    finland = await stack.call(
        "add_transform",
        project_id=project["id"],
        sql=(
            "SELECT sex, survival, survival_lower, survival_upper FROM input_0 "
            "WHERE country = 'Finland' AND period = '2020-2024' ORDER BY sex"
        ),
        inputs=[source_operator["id"]],
        session_id=session["id"],
        note="Finland, latest period",
    )
    assert [column["name"] for column in finland["output"]["columns"]] == [
        "sex",
        "survival",
        "survival_lower",
        "survival_upper",
    ]
    view = await stack.call(
        "create_widget",
        operator_id=finland["id"],
        type="table",
        title="Lung cancer survival in Finland, 2020-2024",
        spec={"columns": ["sex", "survival"]},
        session_id=session["id"],
        note="Men and women side by side",
    )
    widget = view["widget"]
    assert view["url"] == (
        f"/projects/{project['id']}/sessions/{session['id']}?widget={widget['id']}"
    )

    # What the widget shows, fetched by the widget itself, never through the agent.
    data = await stack.call("get_widget_data", widget_id=widget["id"])
    assert [column["name"] for column in data["columns"]] == [
        "sex",
        "survival",
        "survival_lower",
        "survival_upper",
    ]
    # The spec's Nordic comparison: Finland 17.9 (men) and 30.8 (women).
    assert [row[:2] for row in data["rows"]] == [[1, 17.9], [2, 30.8]]
    assert (data["is_scenario"], data["is_stale"], data["truncated"]) == (False, False, False)

    # The session records what the agent did, as the agent, with its notes.
    async with stack.api() as request:
        entries = await (await request.get(SessionService)).entries(UUID(session["id"]))
    assert [(entry.kind.value, entry.text) for entry in entries] == [
        ("operator", "Survival by country, sex and period"),
        ("operator", "Finland, latest period"),
        ("widget", "Men and women side by side"),
    ]
    assert {(entry.actor.kind.value, entry.actor.name) for entry in entries} == {
        ("external_agent", AGENT)
    }

    # Every event went out after the work it names had been committed.
    assert stack.events.unseen == []
    assert stack.events.types == [
        EventType.SESSION_CREATED,
        EventType.SOURCE_REFRESHED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.WIDGET_CREATED,
        EventType.SESSION_ENTRY_ADDED,
        EventType.RUN_STARTED,
        EventType.RUN_FINISHED,
    ]
    refreshed_event = stack.events.bus.published[1]
    assert refreshed_event.payload == {"data_source_id": source["id"], "changed": True}


# Sotkanet's region ids mapped to the wellbeing services counties and joined with their
# boundaries (the recipe of ada.core.services.schema.geo). Starting from the boundaries
# keeps a county without a value (Åland) on the map, as missing.
TO_COUNTIES = """
SELECT b.county_code, b.name, d.period_start, d.period_end, d.value, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id
ORDER BY b.county_code, d.period_start
"""
COUNTY_ROLES = {
    "time": {"start": "period_start", "end": "period_end", "grain": "year"},
    "geo": {"code": "county_code", "system": "statfin", "level": "wellbeing_services_county"},
    "measures": [{"value": "value"}],
}
BELOW_80 = {
    "id": "low",
    "kind": "compare",
    "op": "<",
    "args": [
        {"id": "value", "kind": "column", "column": "value"},
        {"id": "target", "kind": "constant", "value": 80},
    ],
}


def years_asked(outside: Outside) -> list[list[str]]:
    """The years of each request for Sotkanet's data, in order."""
    return [
        request.url.params.get_list("years")
        for request in outside.requests
        if request.url.path == "/rest/1.1/json"
    ]


def latest(data: dict[str, Any]) -> dict[str, float | None]:
    """Each county's value at its latest period, as the map shows it."""
    names = [column["name"] for column in data["columns"]]
    values: dict[str, tuple[str, float | None]] = {}
    for row in data["rows"]:
        record = dict(zip(names, row, strict=True))
        period = record["period_start"] or ""
        if record["county_code"] not in values or period > values[record["county_code"]][0]:
            values[record["county_code"]] = (period, record["value"])
    return {code: value for code, (_, value) in values.items()}


def recovered(request: httpx.Request, response: httpx.Response) -> httpx.Response:
    """Sotkanet's next answer: the recorded one with every county back at 80 % or more."""
    if request.url.path != "/rest/1.1/json":
        return response
    rows = json.loads(response.content)
    for row in rows:
        if row.get("value") is not None:
            row["value"] = max(row["value"], 80.0)
    return httpx.Response(200, headers=response.headers, content=json.dumps(rows).encode())


async def test_an_agent_maps_a_measure_and_follows_it_with_a_report_and_alerts(
    stack: Stack,
) -> None:
    project = await stack.call("create_project", name="Screening")
    sources = [
        await stack.call(
            "register_source", project_id=project["id"], **example.model_dump(mode="json")
        )
        for example in (SOTKANET_BREAST_SCREENING, SOTKANET_REGIONS, WELLBEING_COUNTY_BOUNDARIES)
    ]
    inputs = [
        (
            await stack.call(
                "add_source_operator", project_id=project["id"], data_source_id=source["id"]
            )
        )["id"]
        for source in sources
    ]
    counties = await stack.call(
        "add_transform",
        project_id=project["id"],
        sql=TO_COUNTIES,
        inputs=inputs,
        roles=COUNTY_ROLES,
    )
    assert counties["output"]["roles"]["geo"]["level"] == "wellbeing_services_county"
    widget = (
        await stack.call(
            "create_widget",
            operator_id=counties["id"],
            type="map",
            title="Breast cancer screening participation",
        )
    )["widget"]

    # A dashboard over 2023-2024 with the map pinned.
    dashboard = (await stack.call("create_dashboard", project_id=project["id"], name="Screening"))[
        "dashboard"
    ]
    dashboard = await stack.call(
        "set_dashboard_time_range",
        dashboard_id=dashboard["id"],
        expected_revision=dashboard["revision"],
        start="2023-01-01",
        end="2024-12-31",
    )
    pinned = await stack.call(
        "pin_widget",
        dashboard_id=dashboard["id"],
        widget_id=widget["id"],
        slot="Participation by county",
        expected_revision=dashboard["revision"],
    )
    # The dashboard shows its own copy of the session's map, on the same pipeline.
    [pinned_id] = [slot["widget_id"] for slot in pinned["version"]["slots"]]
    assert pinned_id != widget["id"]

    # The dashboard's run, as POST /dashboards/{id}/runs starts it: the range is pushed
    # down to Sotkanet, which is asked for exactly those two years.
    async with stack.api() as request:
        run = await (await request.get(RunService)).start(
            UUID(project["id"]),
            Actor(kind=ActorKind.USER, name="web"),
            TimeRange(start=date(2023, 1, 1), end=date(2024, 12, 31)),
        )
    data = await stack.call("get_widget_data", widget_id=widget["id"], run_id=str(run.id))
    assert years_asked(stack.outside) == [["2023", "2024"]]
    shown = latest(data)
    # 21 counties, the City of Helsinki and Åland; the spec's gap: 74.3 % in Helsinki,
    # 85.6 % in North Ostrobothnia. Åland has no Sotkanet value and shows as missing.
    assert len(shown) == 23
    assert (shown["90"], shown["19"], shown["91"]) == (74.3, 85.6, None)
    assert len(data["rows"]) == 22 * 2 + 1
    assert (data["is_scenario"], data["is_stale"]) == (False, False)

    # A report of the dashboard: version 1.0.0 with its sources and their fetch times.
    first = await stack.call(
        "generate_report_from_dashboard", dashboard_id=dashboard["id"], name="Screening report"
    )
    assert first["version"]["version"] == "1.0.0"
    assert first["version"]["time_range"] == {"start": "2023-01-01", "end": "2024-12-31"}
    listed = {entry["name"]: entry for entry in first["version"]["content"]["sources"]}
    assert set(listed) == {
        SOTKANET_BREAST_SCREENING.name,
        SOTKANET_REGIONS.name,
        WELLBEING_COUNTY_BOUNDARIES.name,
    }
    sotkanet = listed[SOTKANET_BREAST_SCREENING.name]
    assert sotkanet["fetched_at"] is not None
    assert sotkanet["address"] == SOTKANET_BREAST_SCREENING.address
    assert sotkanet["widget_ids"] == [pinned_id]
    # The stored periods are fresh: freezing the version fetched nothing more.
    assert years_asked(stack.outside) == [["2023", "2024"]]

    # A wider range is a minor version; only the missing year is fetched.
    dashboard = (await stack.call("get_dashboard", dashboard_id=dashboard["id"]))["dashboard"]
    await stack.call(
        "set_dashboard_time_range",
        dashboard_id=dashboard["id"],
        expected_revision=dashboard["revision"],
        start="2022-01-01",
        end="2024-12-31",
    )
    second = await stack.call(
        "generate_report_from_dashboard", dashboard_id=dashboard["id"], name="Screening report"
    )
    assert second["report"]["id"] == first["report"]["id"]
    assert second["version"]["version"] == "1.1.0"
    assert second["versions"] == ["1.0.0", "1.1.0"]
    assert second["version"]["time_range"] == {"start": "2022-01-01", "end": "2024-12-31"}
    assert years_asked(stack.outside) == [["2023", "2024"], ["2022"]]

    # An alert rule on the dashboard: participation below the strategy's 80 %.
    rule = await stack.call(
        "create_alert_rule",
        dashboard_id=dashboard["id"],
        name="Participation below 80 %",
        operator_id=counties["id"],
        formula=BELOW_80,
        key_columns=["county_code"],
    )
    checked = await stack.call("check_alert_rule", rule_id=rule["id"])
    firing = {alert["key"]["county_code"] for alert in checked["changed"]}
    # East Uusimaa 79.8, West Uusimaa 76.1, Vantaa and Kerava 76.7, Helsinki 74.3 in 2024.
    assert firing == {"01", "03", "04", "90"}
    assert {alert["state"] for alert in checked["changed"]} == {"firing"}
    assert all(alert["condition_sql"] for alert in checked["changed"])
    assert stack.events.types.count(EventType.ALERT_FIRING) == 4

    # Sotkanet publishes recovered numbers; a forced refresh fetches them and the next
    # check resolves every alert.
    stack.outside.edit = recovered
    await stack.call("refresh_source", source_id=sources[0]["id"], force=True)
    await stack.broker.wait_all()
    refreshed = [
        event for event in stack.events.bus.published if event.type is EventType.SOURCE_REFRESHED
    ]
    assert refreshed[-1].payload == {"data_source_id": sources[0]["id"], "changed": True}
    checked = await stack.call("check_alert_rule", rule_id=rule["id"])
    assert {alert["key"]["county_code"] for alert in checked["changed"]} == firing
    assert {alert["state"] for alert in checked["changed"]} == {"resolved"}
    assert checked["firing"] == []
    assert stack.events.types.count(EventType.ALERT_RESOLVED) == 4
    feed = await stack.call("list_alerts", project_id=project["id"], state="firing")
    assert feed == []

    # Every event went out after the work it names had been committed.
    assert stack.events.unseen == []
    assert EventType.DASHBOARD_CHANGED in stack.events.types
    assert stack.events.types.count(EventType.REPORT_VERSION_CREATED) == 2


# The demo


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
        lambda: HttpSourceReaders(
            create_client(httpx.MockTransport(outside)), SystemClock(), allow_private=True
        ),
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
