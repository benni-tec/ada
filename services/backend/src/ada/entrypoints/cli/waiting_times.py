"""`ada seed-waits`: waiting times for care across Finland's wellbeing services counties,
read live off the counties' own web pages and put side by side.

Each county publishes its waiting times in a format of its own, and there is no public
comparison. The project reads five pages through Context.dev (one scrape each, as
Markdown), and plain SQL turns them into rows, so no model is called on a refresh and every
number traces back to a page:

- Kainuu's waiting-time page, watched when the platform can receive Context.dev's monitor
  webhooks (ADA_PUBLIC_URL), otherwise refreshed daily;
- the same page as the Wayback Machine archived it on 2026-04-16, read once, which is how
  the queue at Kajaani is known to have grown from about 3.5 to about 5 months;
- Satakunta's and Pohjanmaa's pages, and hoitojonot.fi, an unofficial aggregator.

A dashboard holds callback times per health station side by side, what each county
publishes and how old its data is, and Kajaani's queue in both copies of the page; an alert
rule fires when a station's queue grew by a month or more.

Seeding is idempotent like `seed-demo`. `--refresh` fetches the pages now (five requests,
within Context.dev's ten a minute), reads the widgets and checks the rule.
"""

from dataclasses import dataclass
from datetime import date

from dishka import AsyncContainer

from ada.adapters.sources.examples import DAY, ExampleSource
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.alerts import AlertRule, AlertState, Severity
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, Slot
from ada.core.models.operators import Operator
from ada.core.models.schema import MeasureRole, Roles, TimeRole
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy
from ada.core.models.time import Grain, TimeRange
from ada.core.models.widgets import Widget
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService

PROJECT = "Equal care: waiting times"
SESSION = "Waiting times across wellbeing areas"
DASHBOARD = "Waiting times across wellbeing areas"
RULE = "Queue grew by a month or more"
RANGE = TimeRange(start=date(2026, 1, 1), end=date(2026, 12, 31))

SEED = Actor(kind=ActorKind.SYSTEM, name="ada seed-waits")

KAINUU_URL = "https://hyvinvointialue.kainuu.fi/asiasanat/odottajat-ja-jonottajat"


def _page(name: str, address: str, freshness: FreshnessPolicy) -> ExampleSource:
    return ExampleSource(
        name=name,
        access_kind=AccessKind.WEB,
        address=address,
        format=DataFormat.HTML,
        options={"operation": "scrape", "extract": "pages"},
        freshness=freshness,
    )


DAILY = FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=DAY)
KAINUU = _page("Kainuu: waiting times (live page)", KAINUU_URL, DAILY)
# `id_` asks for the page as archived, without the Wayback Machine's toolbar. Never
# refreshed: it is a record of what the page said then.
KAINUU_ARCHIVED = _page(
    "Kainuu: waiting times, archived 2026-04-16 (Wayback Machine)",
    f"https://web.archive.org/web/20260416023818id_/{KAINUU_URL}",
    FreshnessPolicy(),
)
SATAKUNTA = _page(
    "Satakunta: access to care",
    "https://satakunnanhyvinvointialue.fi/asiointiopas/hoitoonpaasy/",
    DAILY,
)
POHJANMAA = _page(
    "Pohjanmaa: access to care",
    "https://pohjanmaanhyvinvointi.fi/nain-toimimme/asiakkaan-ja-potilaan-oikeudet/hoidon-saatavuus/",
    DAILY,
)
HOITOJONOT = _page("hoitojonot.fi (unofficial aggregator)", "https://hoitojonot.fi/", DAILY)
PAGES = (KAINUU, KAINUU_ARCHIVED, SATAKUNTA, POHJANMAA, HOITOJONOT)

# Finnish month names, for "Lokakuu 2026:" and "kesäkuu 2026.".
_MONTHS = (
    "['tammikuu', 'helmikuu', 'maaliskuu', 'huhtikuu', 'toukokuu', 'kesäkuu', 'heinäkuu', "
    "'elokuu', 'syyskuu', 'lokakuu', 'marraskuu', 'joulukuu']"
)
_NAMED_MONTH = r"(?i)\b([a-zä]+kuu)\s+(\d{4})(:| ?\.)"
_NUMBERED_MONTH = r"Hoitoon pääsy\D{0,8}(\d{1,2})/(\d{4})"

# One row per health station on a county page: the Markdown table rows that end in a
# callback time ("1 tuntia 24 minuuttia"), with the data month and update date the page
# states. Kainuu: station | care guarantee | callback; Satakunta: station | calls |
# same-day share | phone queue | callback.
STATION_ROWS = rf"""
WITH page AS (
    -- Pages write non-breaking spaces into numbers ("7 tuntia"), which \s does not match.
    SELECT replace(string_agg(text, chr(10) ORDER BY page), chr(160), ' ') AS text
    FROM input_0
),
cells AS (
    SELECT list_transform(
        string_split(trim(line, '| '), '|'),
        lambda c: trim(regexp_replace(regexp_replace(regexp_replace(
            c, '\[([^\]]*)\]\([^)]*\)', '\1', 'g'), '\*\*', '', 'g'), '\s+', ' ', 'g'))
    ) AS c
    FROM (SELECT unnest(string_split(text, chr(10))) AS line FROM page)
    WHERE starts_with(trim(line), '|')
),
month AS (
    SELECT
        coalesce(
            make_date(
                TRY_CAST(regexp_extract(text, '{_NUMBERED_MONTH}', 2) AS INTEGER),
                TRY_CAST(regexp_extract(text, '{_NUMBERED_MONTH}', 1) AS INTEGER), 1),
            make_date(
                TRY_CAST(regexp_extract(text, '{_NAMED_MONTH}', 2) AS INTEGER),
                list_position({_MONTHS}, lower(regexp_extract(text, '{_NAMED_MONTH}', 1))), 1)
        ) AS period_start,
        TRY_CAST(TRY_STRPTIME(
            regexp_extract(text, 'päivitetty\s*(\d{{1,2}}\.\d{{1,2}}\.\d{{4}})', 1), '%d.%m.%Y'
        ) AS DATE) AS updated
    FROM page
)
SELECT
    c[1] AS station,
    CASE WHEN len(c) = 3 THEN c[2] END AS care_guarantee,
    TRY_CAST(replace(regexp_extract(c[2], 'noin\s+(\d+(?:,\d+)?)\s*kk', 1), ',', '.') AS DOUBLE)
        AS queue_months,
    coalesce(TRY_CAST(regexp_extract(c[-1], '(\d+)\s*tunti', 1) AS INTEGER), 0) * 60
        + coalesce(TRY_CAST(regexp_extract(c[-1], '(\d+)\s*minuutti', 1) AS INTEGER), 0)
        AS callback_minutes,
    m.period_start,
    last_day(m.period_start) AS period_end,
    m.updated
FROM cells, month AS m
WHERE len(c) IN (3, 5) AND c[1] <> '' AND regexp_matches(c[-1], '\d+\s*(tunti|minuutti)')
"""

_FRESHNESS = """CASE
        WHEN {month} IS NULL THEN 'no date found on the page'
        WHEN date_diff('month', {month}, current_date) <= 2 THEN 'current'
        ELSE printf('stale: data %d months old', date_diff('month', {month}, current_date))
    END"""

# The comparable number: the average callback time per station, in each county's latest
# month. input_0 Kainuu's stations, input_1 Satakunta's.
CALLBACKS = f"""
SELECT
    area,
    station,
    callback_minutes,
    care_guarantee,
    strftime(period_start, '%m/%Y') AS data_month,
    updated AS published,
    {_FRESHNESS.format(month="period_start")} AS freshness
FROM (
    SELECT 'Kainuu' AS area, * FROM input_0
    UNION ALL BY NAME
    SELECT 'Satakunta' AS area, * FROM input_1
)
ORDER BY callback_minutes DESC, area, station
"""
CALLBACK_ROLES = Roles(measures=(MeasureRole(value="callback_minutes"),))

# Months in the queue for a non-urgent doctor's visit, per station and data month, from
# both copies of Kainuu's page. Only stations whose page gives a queue length have rows.
# input_0 the live page's stations, input_1 the archived copy's.
QUEUE = """
SELECT station, period_start, period_end, queue_months, callback_minutes, care_guarantee,
    updated AS published, 'Live page' AS copy
FROM input_0 WHERE queue_months IS NOT NULL
UNION ALL
SELECT station, period_start, period_end, queue_months, callback_minutes, care_guarantee,
    updated AS published, 'Archived copy (Wayback Machine)' AS copy
FROM input_1 WHERE queue_months IS NOT NULL
ORDER BY station, period_start
"""
QUEUE_ROLES = Roles(
    time=TimeRole(start="period_start", end="period_end", grain=Grain.MONTH),
    measures=(MeasureRole(value="queue_months"),),
)

# What each county's page publishes and how old its data is, read off the pages.
# input_0 Kainuu, input_1 Satakunta, input_2 Pohjanmaa, input_3 hoitojonot.fi.
COVERAGE = rf"""
WITH pages AS (
    SELECT 0 AS i, string_agg(text, chr(10) ORDER BY page) AS text FROM input_0
    UNION ALL SELECT 1, string_agg(text, chr(10) ORDER BY page) FROM input_1
    UNION ALL SELECT 2, string_agg(text, chr(10) ORDER BY page) FROM input_2
    UNION ALL SELECT 3, string_agg(text, chr(10) ORDER BY page) FROM input_3
),
facts AS (
    SELECT
        i,
        text,
        len(regexp_extract_all(text, '(?m)^\s*\|.*\|\s*$')) AS table_lines,
        make_date(
            TRY_CAST(regexp_extract(text, '{_NUMBERED_MONTH}', 2) AS INTEGER),
            TRY_CAST(regexp_extract(text, '{_NUMBERED_MONTH}', 1) AS INTEGER), 1)
            AS numbered_month,
        make_date(
            TRY_CAST(regexp_extract(text, '{_NAMED_MONTH}', 2) AS INTEGER),
            list_position({_MONTHS}, lower(regexp_extract(text, '{_NAMED_MONTH}', 1))), 1)
            AS named_month,
        TRY_CAST(TRY_STRPTIME(regexp_extract(
            text, 'päivitetty\s*(\d{{1,2}}\.\d{{1,2}}\.\d{{4}})', 1), '%d.%m.%Y') AS DATE)
            AS updated,
        TRY_CAST(TRY_STRPTIME(regexp_extract(
            text, 'Hoitoonpääsytiedot\s+(\d{{1,2}}\.\d{{1,2}}\.\d{{4}})', 1), '%d.%m.%Y') AS DATE)
            AS pdf_date,
        regexp_extract(
            text, 'Odotusajat\s+(\d{{1,2}}\.\d{{1,2}}\.\s*-\s*\d{{1,2}}\.\d{{1,2}}\.\d{{4}})', 1)
            AS elderly_period,
        TRY_CAST(TRY_STRPTIME(regexp_extract(
            text, 'Odotusajat\s+\d{{1,2}}\.\d{{1,2}}\.\s*-\s*(\d{{1,2}}\.\d{{1,2}}\.\d{{4}})', 1),
            '%d.%m.%Y') AS DATE) AS elderly_end,
        len(regexp_extract_all(text, 'Tietoa ei saatavilla')) AS no_data
    FROM (SELECT i, replace(text, chr(160), ' ') AS text FROM pages)
),
areas AS (
    SELECT 'Kainuu' AS area,
        'Care guarantee and callback time per health station (HTML table)' AS publishes,
        numbered_month AS data_month, updated AS published, 'official' AS publisher,
        NULL AS note
    FROM facts WHERE i = 0
    UNION ALL
    SELECT 'Satakunta',
        'Calls and callback time per health station (HTML table)'
            || CASE WHEN text LIKE '%powerbi.com%'
                THEN '; more in a separate Power BI report' ELSE '' END,
        named_month, NULL, 'official', NULL
    FROM facts WHERE i = 1
    UNION ALL
    SELECT 'Satakunta, elderly services',
        'Waiting times for elderly social services (HTML table)',
        date_trunc('month', elderly_end)::DATE, NULL, 'official',
        printf('Covers %s; %d of 4 services say "Tietoa ei saatavilla" (no data)',
            elderly_period, no_data)
    FROM facts WHERE i = 1 AND elderly_end IS NOT NULL
    UNION ALL
    SELECT 'Pohjanmaa',
        CASE WHEN table_lines = 0
            THEN 'No table on the page: links to THL reports and a PDF'
            ELSE 'A table on the page' END,
        date_trunc('month', pdf_date)::DATE, pdf_date, 'official',
        'The numbers are only in the linked PDF and on THL'
    FROM facts WHERE i = 2
    UNION ALL
    SELECT 'hoitojonot.fi',
        'Share of visits within 7 days and after 30 days, every station (from THL Avohilmo)',
        named_month, NULL, 'unofficial',
        'Third-party site; realised waits, not a live queue'
    FROM facts WHERE i = 3
)
SELECT
    area,
    publishes,
    publisher,
    strftime(data_month, '%m/%Y') AS data_month,
    published,
    {_FRESHNESS.format(month="data_month")}
        || CASE WHEN publisher = 'unofficial' THEN ', unofficial' ELSE '' END AS freshness,
    note
FROM areas
"""

GREW_A_MONTH: JsonObject = {
    "id": "grew",
    "kind": "compare",
    "op": ">=",
    "args": [
        {
            "id": "change",
            "kind": "change",
            "args": [{"id": "months", "kind": "column", "column": "queue_months"}],
        },
        {"id": "one_month", "kind": "constant", "value": 1},
    ],
}


@dataclass
class Waits:
    project_id: Id
    dashboard: Dashboard
    widgets: tuple[Widget, ...]
    rule: AlertRule


async def seed_waits(container: AsyncContainer, refresh: bool = False) -> Id:
    async with container() as request:
        project_id, sources = await _project(
            await request.get(ProjectService), await request.get(SourceService)
        )
    async with container() as request:
        waits = await _build(request, project_id, sources)
    if refresh:
        await _fetch(container, waits)
    return project_id


async def _project(projects: ProjectService, sources: SourceService) -> tuple[Id, dict[str, Id]]:
    project = next((p for p in await projects.list() if p.name == PROJECT), None)
    if project is None:
        project = await projects.create(PROJECT)
        print(f"Created project {PROJECT!r}: {project.id}")
    else:
        print(f"Project {PROJECT!r} exists: {project.id}")
    registered = {source.name: source.id for source in await sources.list(project.id)}
    for page in PAGES:
        if page.name not in registered:
            source = await sources.register(project.id, **page.registration())
            registered[page.name] = source.id
            if page is KAINUU:
                try:
                    await sources.watch(source.id)
                    print("  watching Kainuu's page: Context.dev calls back when it changes")
                except Exception as error:  # No public URL in development: daily ttl.
                    print(f"  not watching Kainuu's page ({error}); it is refreshed daily")
        print(f"  source {registered[page.name]}  {page.name}")
    return project.id, registered


async def _build(request: AsyncContainer, project_id: Id, sources: dict[str, Id]) -> Waits:
    pipelines = await request.get(PipelineService)
    sessions = await request.get(SessionService)
    widgets = await request.get(WidgetService)
    dashboards = await request.get(DashboardService)
    alerts = await request.get(AlertService)

    async def page(source: ExampleSource) -> Operator:
        return await pipelines.add_source(project_id, sources[source.name], SEED)

    async def transform(sql: str, inputs: list[Operator], roles: Roles | None = None) -> Operator:
        return await pipelines.add_transform(
            project_id, sql, [i.id for i in inputs], SEED, roles=roles
        )

    # The same SQL reads every county page with a station table, and both copies of Kainuu's.
    kainuu = await transform(STATION_ROWS, [await page(KAINUU)])
    archived = await transform(STATION_ROWS, [await page(KAINUU_ARCHIVED)])
    satakunta = await transform(STATION_ROWS, [await page(SATAKUNTA)])
    callbacks = await transform(CALLBACKS, [kainuu, satakunta], CALLBACK_ROLES)
    queue = await transform(QUEUE, [kainuu, archived], QUEUE_ROLES)
    coverage = await transform(
        COVERAGE,
        [await page(KAINUU), await page(SATAKUNTA), await page(POHJANMAA), await page(HOITOJONOT)],
    )

    session = next((s for s in await sessions.list(project_id) if s.title == SESSION), None)
    if session is None:
        session = await sessions.create(project_id, SESSION)
        await sessions.add_message(
            session.id,
            "Seeded: the wellbeing areas' own waiting-time pages, read through Context.dev "
            "and parsed with SQL, side by side with their sources and the age of their data.",
            SEED,
        )
        for operator, note in (
            (callbacks, "Callback time per health station, Kainuu and Satakunta"),
            (queue, "Kajaani's queue in the live page and the archived copy"),
            (coverage, "What each page publishes, and how old its data is"),
        ):
            await sessions.record_operator(session.id, operator.id, note, SEED)

    existing = {(w.operator_id, w.title): w for w in await widgets.list(project_id)}

    async def widget(operator: Operator, title: str, spec: JsonObject, note: str) -> Widget:
        found = existing.get((operator.id, title))
        if found is not None:
            return found
        return await widgets.create(
            project_id,
            operator.id,
            "table",
            title,
            SEED,
            spec=spec,
            note=note,
            session_id=session.id,
        )

    callback_table = await widget(
        callbacks,
        "Callback time per health station, latest month",
        {
            "columns": [
                "area",
                "station",
                "callback_minutes",
                "care_guarantee",
                "data_month",
                "freshness",
            ],
            "labels": {
                "area": "Area",
                "station": "Health station",
                "callback_minutes": "Callback, min",
                "care_guarantee": "Care guarantee",
                "data_month": "Data month",
                "freshness": "Freshness",
            },
            "format": {"callback_minutes": "integer"},
        },
        "The one number both counties publish per station: the average callback time",
    )
    coverage_table = await widget(
        coverage,
        "What each wellbeing area publishes",
        {
            "columns": ["area", "publishes", "data_month", "freshness", "note"],
            "labels": {
                "area": "Source",
                "publishes": "Publishes",
                "data_month": "Data month",
                "freshness": "Freshness",
                "note": "Note",
            },
        },
        "Every page has its own format; some have no numbers, some old ones",
    )
    queue_table = await widget(
        queue,
        "Kajaani: months in the queue for a non-urgent doctor's visit",
        {
            "columns": ["copy", "period_start", "queue_months", "callback_minutes", "published"],
            "labels": {
                "copy": "Copy of the page",
                "period_start": "Data month",
                "queue_months": "Queue, months",
                "callback_minutes": "Callback, min",
                "published": "Page updated",
            },
            "format": {"callback_minutes": "integer"},
            "decimals": 1,
        },
        "The live page against the Wayback Machine's copy of 2026-04-16",
    )
    tables = (callback_table, coverage_table, queue_table)

    dashboard = next((d for d in await dashboards.list(project_id) if d.name == DASHBOARD), None)
    if dashboard is None:
        dashboard = await dashboards.create(project_id, DASHBOARD, SEED)
    if dashboard.default_time_range != RANGE:
        dashboard = await dashboards.set_default_time_range(dashboard.id, RANGE, dashboard.revision)
    if await dashboards.current(dashboard.id) is None:
        slots = (
            Slot(
                name="Callbacks",
                widget_id=callback_table.id,
                layout={"x": 0, "y": 0, "w": 7, "h": 8},
            ),
            Slot(name="Kajaani", widget_id=queue_table.id, layout={"x": 7, "y": 0, "w": 5, "h": 4}),
            Slot(
                name="Sources", widget_id=coverage_table.id, layout={"x": 7, "y": 4, "w": 5, "h": 4}
            ),
        )
        await dashboards.edit(dashboard.id, slots, dashboard.revision, SEED)
        dashboard = await dashboards.get(dashboard.id)
    if session.panel_dashboard_id != dashboard.id:
        await sessions.show_dashboard(session.id, dashboard.id, session.revision)

    rule = next((r for r in await alerts.list_rules(dashboard.id) if r.name == RULE), None)
    if rule is None:
        rule = await alerts.create_rule(
            dashboard.id, RULE, queue.id, GREW_A_MONTH, ["station"], severity=Severity.WARNING
        )
    print(f"  dashboard {dashboard.id}  {DASHBOARD}")
    print(f"  rule      {rule.id}  {RULE}")
    return Waits(project_id, dashboard, tables, rule)


async def _fetch(container: AsyncContainer, waits: Waits) -> None:
    """Fetch the pages through the dashboard's widgets, then check the rule; each step in
    its own unit of work, so one page that fails leaves the others."""
    print("Fetching the pages:")
    async with container() as request:
        run = await (await request.get(RunService)).start(
            waits.project_id, SEED, waits.dashboard.default_time_range
        )
    for widget in waits.widgets:
        try:
            async with container() as request:
                data = await (await request.get(WidgetService)).data(widget.id, run.id)
            print(f"  {widget.title}: {len(data.rows)} rows")
        except Exception as error:
            print(f"  {widget.title} failed: {error}")
    try:
        async with container() as request:
            alerts = await request.get(AlertService)
            await alerts.check(waits.rule.id)
            firing = [
                a
                for a in await alerts.alerts(waits.project_id, AlertState.FIRING)
                if a.rule_id == waits.rule.id
            ]
        print(f"  {RULE}: {len(firing)} firing")
    except Exception as error:
        print(f"  {RULE} failed: {error}")
