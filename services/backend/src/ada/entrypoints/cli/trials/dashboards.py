"""Registry counts for trial units, and recruiting sites to discuss with an oncologist."""

from typing import TYPE_CHECKING

from dishka import AsyncContainer

from ada.core.models.actors import Actor
from ada.core.models.attachments import AttachmentKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, Slot
from ada.core.models.operators import Operator
from ada.core.models.widgets import Widget
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.widgets import WidgetService

if TYPE_CHECKING:
    from ada.entrypoints.cli.trials.seed import TrialSteps

DOORS = "Trial doors: Nordic cancer trials Finland lacks"
NEAR_YOU = "Open cancer trials near you"

DISTANCES = {"km_helsinki": "Helsinki, km", "km_kuopio": "Kuopio, km", "km_oulu": "Oulu, km"}
LABELS = {
    "title": "Trial",
    "url": "Registry URL",
    "phase": "Phase",
    "cancer_groups": "Cancer groups",
    "sponsor": "Sponsor",
    "open_countries": "Recruiting countries",
    "nearest_facility": "Nearest facility to Helsinki",
    "nearest_city": "Nearest city to Helsinki",
    "facility": "Facility",
    "city": "City",
    "country": "Country",
    "sex": "Sex (registry)",
    "min_age_years": "Minimum age, years",
    "max_age_years": "Maximum age, years",
    "eligibility": "Eligibility as written",
    "status_fi": "Finland status [inferred]",
    "recruiting_in": "Recruiting elsewhere",
    "decision_date": "Decision date",
    "registry": "Registry",
    "cancer_group": "Cancer group",
    "trials": "Trials",
    "per_million": "Trials per million",
    "rate_ratio_fi": "Finland rate / country rate",
    "finland_trials": "Finland trials",
    "finland_per_million": "Finland per million",
    "nordic_per_million": "SE+NO+DK per million",
    "more_trials_needed": "More trials needed",
    "population_source": "Population source",
    **DISTANCES,
}


MORE_NEEDED = "More recruiting trials Finland needs to match SE/NO/DK"
# Pooled SE+NO+DK rate times Finland's population, rounded up.
MORE_NEEDED_SQL = """
WITH nb AS (
    SELECT registry, cancer_group, sum(trials) / sum(population_m) AS nordic_per_million
    FROM input_0 WHERE country IN ('Sweden', 'Norway', 'Denmark') GROUP BY ALL
)
SELECT f.registry, f.cancer_group,
       f.trials AS finland_trials,
       round(f.per_million, 1) AS finland_per_million,
       round(nb.nordic_per_million, 1) AS nordic_per_million,
       greatest(0, ceil((nb.nordic_per_million - f.per_million) * f.population_m))::INTEGER
           AS more_trials_needed,
       f.population_source
FROM input_0 f JOIN nb USING (registry, cancer_group)
WHERE f.country = 'Finland' AND f.cancer_group IN ('all', 'lung', 'pancreas', 'liver')
ORDER BY CASE f.cancer_group WHEN 'all' THEN 0 WHEN 'lung' THEN 1 WHEN 'pancreas' THEN 2 ELSE 3
    END, f.registry
"""
MORE_NEEDED_COLUMNS = [
    "registry",
    "cancer_group",
    "finland_trials",
    "finland_per_million",
    "nordic_per_million",
    "more_trials_needed",
    "population_source",
]


def _table(columns: list[str]) -> JsonObject:
    return {
        "columns": columns,
        "labels": {c: LABELS[c] for c in columns},
        "format": {c: "integer" for c in columns if c in DISTANCES},
        "decimals": 2,
    }


async def create_dashboards(
    request: AsyncContainer, project_id: Id, session_id: Id, steps: TrialSteps, actor: Actor
) -> tuple[Dashboard, Dashboard]:
    """Create both dashboards once and attach them to the seed's session on every run."""
    pipelines = await request.get(PipelineService)
    widgets = await request.get(WidgetService)
    dashboards = await request.get(DashboardService)
    attachments = await request.get(AttachmentService)
    existing = {
        (w.operator_id, w.title): w for w in await widgets.list(project_id) if w.copied_from is None
    }

    async def view(sql: str, *inputs: Operator) -> Operator:
        return await pipelines.add_transform(project_id, sql, [i.id for i in inputs], actor)

    async def widget(operator: Operator, kind: str, title: str, spec: JsonObject) -> Widget:
        found = existing.get((operator.id, title))
        if found is not None:
            return found
        return await widgets.create(
            project_id, operator.id, kind, title, actor, spec=spec, session_id=session_id
        )

    rates = await widget(
        steps.trial_rates,
        "chart",
        "Recruiting trials per million",
        {
            "transform": [{"filter": "datum.cancer_group === 'all'"}],
            "facet": {"column": {"field": "registry", "type": "nominal", "title": "Registry"}},
            "spec": {
                "width": 300,
                "height": 220,
                "mark": "bar",
                "encoding": {
                    "x": {
                        "field": "country",
                        "type": "nominal",
                        "title": "Country",
                        "axis": {"labelAngle": -25},
                    },
                    "y": {
                        "field": "per_million",
                        "type": "quantitative",
                        "title": "Trials per million",
                    },
                    "color": {
                        "condition": {"test": "datum.country === 'Finland'", "value": "#0072B2"},
                        "value": "#999999",
                    },
                    "tooltip": [
                        {"field": "country"},
                        {"field": "trials", "type": "quantitative"},
                        {"field": "per_million", "type": "quantitative", "format": ".1f"},
                    ],
                },
            },
        },
    )
    cancers = await view(
        "SELECT * FROM input_0 WHERE cancer_group IN ('lung', 'pancreas', 'liver') "
        "ORDER BY registry, cancer_group, country",
        steps.trial_rates,
    )
    cancer_table = await widget(
        cancers,
        "table",
        "Per million: lung, pancreas, liver",
        _table(["registry", "cancer_group", "country", "trials", "per_million", "rate_ratio_fi"]),
    )
    doors = await view(
        "SELECT * FROM input_0 ORDER BY km_helsinki NULLS LAST, nct_id", steps.trial_doors
    )
    doors_table = await widget(
        doors,
        "table",
        "Abroad, no Finnish site",
        _table(
            [
                "title",
                "url",
                "phase",
                "cancer_groups",
                "sponsor",
                "open_countries",
                "nearest_facility",
                "nearest_city",
                *DISTANCES,
            ]
        ),
    )
    sites = await view(
        "SELECT c.*, CASE WHEN t.has_fi_site THEN 'Trial with a Finnish site' "
        "ELSE 'Trial without a Finnish site' END AS site_group "
        "FROM input_0 c JOIN input_1 t USING (nct_id) "
        "WHERE c.lat IS NOT NULL AND c.lon IS NOT NULL",
        steps.case_trials,
        steps.trials,
    )
    site_map = await widget(
        sites,
        "chart",
        "Recruiting Nordic sites",
        {
            "projection": {"type": "mercator"},
            "mark": {"type": "point", "size": 70, "opacity": 0.7},
            "encoding": {
                "longitude": {"field": "lon", "type": "quantitative"},
                "latitude": {"field": "lat", "type": "quantitative"},
                "color": {"field": "country", "type": "nominal", "title": "Country"},
                "shape": {"field": "site_group", "type": "nominal", "title": "Finnish presence"},
                "tooltip": [
                    {"field": field, "title": title}
                    for field, title in (
                        ("facility", "Facility"),
                        ("city", "City"),
                        ("country", "Country"),
                        ("title", "Trial"),
                        ("site_group", "Finnish presence"),
                    )
                ],
            },
        },
    )
    needed = await widget(
        await view(MORE_NEEDED_SQL, steps.trial_rates),
        "table",
        MORE_NEEDED,
        _table(MORE_NEEDED_COLUMNS),
    )
    pending = await widget(
        steps.ctis_finland_pending,
        "table",
        "Finland: recruitment pending",
        _table(["title", "url", "sponsor", "phase", "status_fi", "recruiting_in", "decision_date"]),
    )
    definitions = await widget(
        steps.trial_rates,
        "text",
        "Sources and definitions",
        {
            "markdown": (
                "Counts from ClinicalTrials.gov and EU CTIS; CTIS status codes inferred; "
                "populations [unverified]. ClinicalTrials.gov counts trials marked RECRUITING "
                "with a recruiting site in the country, CTIS counts oncology trials with country "
                "status 4, and doors have a recruiting Swedish, Norwegian or Danish site and no "
                "Finnish site at all; distances are straight-line kilometres and the map omits "
                "sites without registry coordinates."
            )
        },
    )
    nearby = await view(
        "SELECT city, km_helsinki, km_kuopio, km_oulu, title, eligibility, url FROM input_0 "
        "ORDER BY least(km_helsinki, km_kuopio, km_oulu) NULLS LAST",
        steps.case_trials,
    )
    patient_table = await widget(
        nearby,
        "table",
        "Recruiting cancer trials and sites",
        _table(["city", *DISTANCES, "title", "eligibility", "url"]),
    )
    advice = await widget(
        steps.case_trials,
        "text",
        "Discuss these trials with your oncologist",
        {
            "markdown": "This list shows trials that registries say are recruiting. "
            "It does not judge whether you are eligible. Take it to your oncologist."
        },
    )

    async def dashboard(name: str, content: list[tuple[Widget, int, int, int, int]]) -> Dashboard:
        found = next((d for d in await dashboards.list(project_id) if d.name == name), None)
        if found is None:
            found = await dashboards.create(project_id, name, actor)
        slots = [
            Slot(
                name=w.title,
                widget_id=w.id,
                layout={"x": x, "y": y, "w": width, "h": height},
            )
            for w, x, y, width, height in content
        ]
        current = await dashboards.current(found.id)
        current_slots = []
        if current is not None:
            for slot in current.slots:
                placed = await widgets.get(slot.widget_id) if slot.widget_id else None
                current_slots.append(
                    slot.model_copy(update={"widget_id": placed.copied_from or placed.id})
                    if placed
                    else slot
                )
        if current is None or current_slots != slots:
            await dashboards.edit(found.id, slots, found.revision, actor)
            found = await dashboards.get(found.id)
        await attachments.attach(session_id, AttachmentKind.DASHBOARD, str(found.id), actor)
        return found

    return (
        await dashboard(
            DOORS,
            [
                (definitions, 0, 0, 12, 3),
                (rates, 0, 3, 12, 6),
                (needed, 0, 9, 12, 5),
                (cancer_table, 0, 14, 6, 7),
                (site_map, 6, 14, 6, 7),
                (doors_table, 0, 21, 12, 8),
                (pending, 0, 29, 12, 7),
            ],
        ),
        await dashboard(NEAR_YOU, [(advice, 0, 0, 12, 3), (patient_table, 0, 3, 12, 10)]),
    )
