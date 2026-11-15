"""`ada seed-demo`: the health demo's project, with the public sources it reads and a ready
demo built on them: a map and a table of breast cancer screening participation by
wellbeing services county on a dashboard, an alert rule on it, a session that made them,
and a line chart of lung cancer survival.

Seeding is idempotent: what exists (found by name or, for operators, by identity) is
kept, what is missing is added. Building the demo needs no data: operators are described
from the sources' declared schemas. `--refresh` then fetches what the demo shows, in this
process (a handful of requests to the free public APIs), so the dashboard, its report and
its alerts are there at once; the other sources are queued for the worker.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from dishka import AsyncContainer

from ada.adapters.sources.examples import (
    EXAMPLES,
    NORDCAN_LUNG_SURVIVAL,
    SOTKANET_BREAST_SCREENING,
    SOTKANET_REGIONS,
    WELLBEING_COUNTY_BOUNDARIES,
    ExampleSource,
)
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import AlertRule, AlertState, Severity
from ada.core.models.attachments import AttachmentKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, Slot
from ada.core.models.operators import Operator
from ada.core.models.schema import GeoRole, MeasureRole, Roles, TimeRole
from ada.core.models.sources import DataSource
from ada.core.models.time import Grain, TimeRange
from ada.core.models.widgets import Widget
from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.reports import ReportService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.curated import seed_cases, seed_curated

DEMO_PROJECT = "Nordic cancer care"
DEMO_SESSION = "Screening participation and lung cancer survival"
DEMO_DASHBOARD = "Screening participation"
DEMO_REPORT = "Screening participation report"
DEMO_RULE = "Participation below 80 %"
# Three years: the map and the alert show the latest, the table the same.
DEMO_RANGE = TimeRange(start=date(2022, 1, 1), end=date(2024, 12, 31))

SEED = Actor(kind=ActorKind.SYSTEM, name="ada seed-demo")

# Sotkanet's region ids mapped to the wellbeing services counties (SOTKANET_REGIONS) and
# joined with their boundaries, for the latest year of the run's range. Starting from the
# boundaries keeps a county without a value (Åland runs its own screening) on the map, as
# missing; the year is picked in the join for the same reason.
TO_COUNTIES = """
SELECT b.county_code, b.name, d.period_start, d.period_end, d.value, d.count, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN (
    SELECT * FROM input_0 WHERE period_end = (SELECT max(period_end) FROM input_0)
) AS d ON d.region = r.sotkanet_id
ORDER BY b.county_code
"""
COUNTY_ROLES = Roles(
    time=TimeRole(start="period_start", end="period_end", grain=Grain.YEAR),
    geo=GeoRole(code="county_code", system="statfin", level="wellbeing_services_county"),
    measures=(MeasureRole(value="value"),),
)

# The spec's Nordic comparison, Finland's side: men and women by five-year window.
FINLAND_LUNG_SURVIVAL = """
SELECT CASE sex WHEN 1 THEN 'Men' ELSE 'Women' END AS sex, period, period_start, period_end,
    survival, survival_lower, survival_upper
FROM input_0
WHERE country = 'Finland'
ORDER BY sex, period_start
"""
SURVIVAL_ROLES = Roles(
    time=TimeRole(start="period_start", end="period_end"),
    measures=(MeasureRole(value="survival", lower="survival_lower", upper="survival_upper"),),
)

# Strategy objective 2: 80 % participation in every wellbeing services county.
BELOW_80 = {
    "id": "below",
    "kind": "compare",
    "op": "<",
    "args": [
        {"id": "participation", "kind": "column", "column": "value"},
        {"id": "target", "kind": "constant", "value": 80},
    ],
}

MAP_TITLE = "Breast cancer screening participation by county, %"
TABLE_TITLE = "Participation by county, latest year"
CHART_TITLE = "Lung cancer five-year survival in Finland, %"


@dataclass
class Demo:
    project_id: Id
    sources: dict[str, DataSource]
    dashboard: Dashboard
    rule: AlertRule
    widgets: tuple[Widget, ...]
    chart: Widget


# Vega-Lite: survival per sex over the five-year windows, with its confidence interval.
LUNG_SURVIVAL_CHART: JsonObject = {
    "encoding": {
        "x": {
            "field": "period_start",
            "type": "temporal",
            "title": "Five-year window (start)",
            "axis": {"format": "%Y"},
        },
        "color": {"field": "sex", "type": "nominal", "title": None, "legend": {"orient": "top"}},
    },
    "layer": [
        {
            "mark": {"type": "area", "opacity": 0.2},
            "encoding": {
                "y": {
                    "field": "survival_lower",
                    "type": "quantitative",
                    "title": "Five-year survival, %",
                },
                "y2": {"field": "survival_upper"},
            },
        },
        {
            "mark": {"type": "line", "point": True},
            "encoding": {"y": {"field": "survival", "type": "quantitative"}},
        },
    ],
}


async def seed_demo(container: AsyncContainer, refresh: bool = False) -> Id:
    """Create what is missing of the demo project and print what it holds. With `refresh`,
    fetch the demo's data now and queue a refresh of the other sources for the worker."""
    async with container() as request:
        project_id, sources = await _project(
            await request.get(ProjectService),
            await request.get(SourceService),
            await request.get(PipelineService),
        )
    # Its own unit of work: the sources are committed before anything is built on them.
    async with container() as request:
        demo = await _demo(request, project_id, sources)
    # The curated dashboards and the cases they read (curated.py).
    case_types = await seed_cases(container, project_id, SEED)
    curated = await seed_curated(container, project_id, case_types, SEED)

    if refresh:
        fetched = await _fetch(container, demo)
        # Queued after everything above has committed, so the worker finds it.
        dispatcher = await container.get(TaskDispatcher)
        others = [source.id for source in sources.values() if source.id not in fetched]
        others += [id for id in curated if id not in fetched]
        for source_id in others:
            await dispatcher.refresh_source(source_id, force=True)
        print(f"Queued a refresh of {len(others)} more sources; the worker fetches them.")
    return project_id


async def _project(
    projects: ProjectService, sources: SourceService, pipelines: PipelineService
) -> tuple[Id, dict[str, DataSource]]:
    existing = [p for p in await projects.list() if p.name == DEMO_PROJECT]
    if existing:
        project = existing[0]
        print(f"Project {DEMO_PROJECT!r} exists: {project.id}")
    else:
        project = await projects.create(DEMO_PROJECT)
        print(f"Created project {DEMO_PROJECT!r}: {project.id}")
    registered = {source.name: source for source in await sources.list(project.id)}
    for example in EXAMPLES:
        source = registered.get(example.name)
        if source is not None and await _outdated(source, example, pipelines):
            # Registered by an older seed, e.g. without the period columns. Its source
            # operator keeps the output it was registered with (operators never change),
            # so an edit would not reach the pipelines: register it anew, keep the old one.
            await sources.update(
                source.id, source.revision, name=f"{example.name} (before {date.today()})"
            )
            source = None
        if source is None:
            registered[example.name] = await sources.register(project.id, **example.registration())
    for source in registered.values():
        print(f"  source {source.id}  {source.name}")
    return project.id, registered


async def _outdated(source: DataSource, example: ExampleSource, pipelines: PipelineService) -> bool:
    operator = await pipelines.add_source(source.project_id, source.id, SEED)
    declared = example.declared_schema
    return (
        (source.address, source.options, source.freshness)
        != (
            example.address,
            example.options,
            example.freshness,
        )
        or declared is None
        or (operator.output.columns, operator.output.roles) != (declared.columns, declared.roles)
    )


async def _demo(request: AsyncContainer, project_id: Id, sources: dict[str, DataSource]) -> Demo:
    pipelines = await request.get(PipelineService)
    sessions = await request.get(SessionService)
    widgets = await request.get(WidgetService)
    dashboards = await request.get(DashboardService)
    alerts = await request.get(AlertService)
    attachments = await request.get(AttachmentService)

    async def source(example: ExampleSource) -> Operator:
        return await pipelines.add_source(project_id, sources[example.name].id, SEED)

    # Adding an operator that exists returns it: the same SQL over the same inputs.
    counties = await pipelines.add_transform(
        project_id,
        TO_COUNTIES,
        [
            (await source(SOTKANET_BREAST_SCREENING)).id,
            (await source(SOTKANET_REGIONS)).id,
            (await source(WELLBEING_COUNTY_BOUNDARIES)).id,
        ],
        SEED,
        roles=COUNTY_ROLES,
    )
    survival = await pipelines.add_transform(
        project_id,
        FINLAND_LUNG_SURVIVAL,
        [(await source(NORDCAN_LUNG_SURVIVAL)).id],
        SEED,
        roles=SURVIVAL_ROLES,
    )

    session = next((s for s in await sessions.list(project_id) if s.title == DEMO_SESSION), None)
    if session is None:
        session = await sessions.create(project_id, DEMO_SESSION)
        await sessions.add_message(
            session.id,
            "Seeded demo: breast cancer screening participation against the 80 % target, "
            "and lung cancer survival in Finland.",
            SEED,
        )
        await sessions.record_operator(
            session.id,
            counties.id,
            "Sotkanet's regions mapped to the wellbeing services counties, latest year, "
            "with their boundaries",
            SEED,
        )
        await sessions.record_operator(
            session.id, survival.id, "Finland's lung cancer survival, men and women", SEED
        )
    # The session's widgets: the dashboard holds copies of them (copied_from).
    project_widgets = await widgets.list(project_id)
    existing = {(w.operator_id, w.title): w for w in project_widgets if w.session_id == session.id}
    original = {w.id: w.copied_from or w.id for w in project_widgets}

    async def widget(
        operator: Operator, type: str, title: str, spec: JsonObject, note: str
    ) -> Widget:
        found = existing.get((operator.id, title))
        if found is not None:
            # A demo seeded with older widget specs gets the current ones.
            if (found.type, found.spec, found.note) != (type, spec, note):
                return await widgets.update(found.id, type=type, spec=spec, note=note)
            return found
        return await widgets.create(
            project_id, operator.id, type, title, SEED, spec=spec, note=note, session_id=session.id
        )

    map_widget = await widget(
        counties, "map", MAP_TITLE, {"value": "value"}, "Each county against the 80 % target"
    )
    table = await widget(
        counties,
        "table",
        TABLE_TITLE,
        {
            "columns": ["name", "value", "count"],
            "labels": {"name": "County", "value": "Participation", "count": "Women screened"},
            "format": {"value": "percent", "count": "integer"},
            "decimals": 1,
        },
        "The same numbers, with the number of women screened",
    )
    chart = await widget(
        survival,
        "chart",
        CHART_TITLE,
        LUNG_SURVIVAL_CHART,
        "Finland's side of the Nordic comparison; shaded: 95% confidence interval. NORDCAN",
    )

    dashboard = next(
        (d for d in await dashboards.list(project_id) if d.name == DEMO_DASHBOARD), None
    )
    if dashboard is None:
        dashboard = await dashboards.create(project_id, DEMO_DASHBOARD, SEED)
    if dashboard.default_time_range != DEMO_RANGE:
        dashboard = await dashboards.set_default_time_range(
            dashboard.id, DEMO_RANGE, dashboard.revision
        )
    slots = (
        Slot(name="Map", widget_id=map_widget.id, layout={"x": 0, "y": 0, "w": 7, "h": 6}),
        Slot(name="By county", widget_id=table.id, layout={"x": 7, "y": 0, "w": 5, "h": 6}),
    )
    current = await dashboards.current(dashboard.id)
    if current is None or [
        (s.name, original.get(s.widget_id) if s.widget_id else None) for s in current.slots
    ] != [(s.name, s.widget_id) for s in slots]:
        await dashboards.edit(dashboard.id, slots, dashboard.revision, SEED)
        dashboard = await dashboards.get(dashboard.id)
    # Shown beside the session; attaching again changes nothing.
    await attachments.attach(session.id, AttachmentKind.DASHBOARD, str(dashboard.id), SEED)

    rule = next((r for r in await alerts.list_rules(dashboard.id) if r.name == DEMO_RULE), None)
    if rule is None:
        rule = await alerts.create_rule(
            dashboard.id,
            DEMO_RULE,
            counties.id,
            BELOW_80,
            ["county_code"],
            severity=Severity.WARNING,
        )

    print(f"  session   {session.id}  {DEMO_SESSION}")
    print(f"  dashboard {dashboard.id}  {DEMO_DASHBOARD}")
    print(f"  rule      {rule.id}  {DEMO_RULE}")
    return Demo(project_id, sources, dashboard, rule, (map_widget, table), chart)


async def _fetch(container: AsyncContainer, demo: Demo) -> set[Id]:
    """Fetch what the demo shows and finish what needs data, each step in its own unit of
    work so one failing source leaves the others. Returns the sources it fetched."""
    fetched: set[Id] = set()
    by_name = demo.sources

    async def step(
        what: str,
        sources: tuple[ExampleSource, ...],
        work: Callable[[AsyncContainer], Awaitable[str]],
    ) -> None:
        try:
            async with container() as request:
                message = await work(request)
            fetched.update(by_name[example.name].id for example in sources)
            print(f"  {what}: {message}")
        except Exception as error:  # A public API may be down; the rest still works.
            print(f"  {what} failed: {error}")

    async def dashboard_run(request: AsyncContainer) -> str:
        runs = await request.get(RunService)
        widgets = await request.get(WidgetService)
        run = await runs.start(demo.project_id, SEED, demo.dashboard.default_time_range)
        data = await widgets.data(demo.widgets[0].id, run.id)
        return f"run {run.id}, {len(data.rows)} counties"

    async def report(request: AsyncContainer) -> str:
        reports = await request.get(ReportService)
        existing = [
            r
            for r in await reports.list(demo.project_id)
            if r.dashboard_id == demo.dashboard.id and r.name == DEMO_REPORT
        ]
        if existing:
            return f"exists, {existing[0].id}"
        version = await reports.generate_from_dashboard(demo.dashboard.id, DEMO_REPORT, SEED)
        return f"{version.report_id} version {version.version}"

    async def check(request: AsyncContainer) -> str:
        alerts = await request.get(AlertService)
        await alerts.check(demo.rule.id)
        firing = [
            a
            for a in await alerts.alerts(demo.project_id, AlertState.FIRING)
            if a.rule_id == demo.rule.id
        ]
        return f"{len(firing)} counties below 80 %"

    async def chart(request: AsyncContainer) -> str:
        data = await (await request.get(WidgetService)).data(demo.chart.id)
        return f"{len(data.rows)} rows"

    print("Fetching the demo's data:")
    screening = (SOTKANET_BREAST_SCREENING, SOTKANET_REGIONS, WELLBEING_COUNTY_BOUNDARIES)
    await step("dashboard", screening, dashboard_run)
    await step("report", (), report)
    await step("alerts", (), check)
    await step("lung cancer survival", (NORDCAN_LUNG_SURVIVAL,), chart)
    return fetched
