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
    **DISTANCES,
}


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
        "Recruiting cancer trials per million",
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
        "Lung, pancreas and liver trial rates",
        _table(["registry", "cancer_group", "country", "trials", "per_million", "rate_ratio_fi"]),
    )
    doors = await view(
        "SELECT * FROM input_0 ORDER BY km_helsinki NULLS LAST, nct_id", steps.trial_doors
    )
    doors_table = await widget(
        doors,
        "table",
        "Recruiting abroad, no Finnish site",
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
        "Recruiting Nordic sites with registry coordinates",
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
    pending = await widget(
        steps.ctis_finland_pending,
        "table",
        "Listed for Finland, not recruiting yet",
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
    patient_table = await widget(
        steps.case_trials,
        "table",
        "Recruiting cancer trials and sites",
        _table(
            [
                "title",
                "url",
                "cancer_groups",
                "phase",
                "facility",
                "city",
                "country",
                *DISTANCES,
                "sex",
                "min_age_years",
                "max_age_years",
                "eligibility",
            ]
        ),
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
        if await dashboards.current(found.id) is None:
            await dashboards.edit(
                found.id,
                [
                    Slot(
                        name=w.title,
                        widget_id=w.id,
                        layout={"x": x, "y": y, "w": width, "h": height},
                    )
                    for w, x, y, width, height in content
                ],
                found.revision,
                actor,
            )
            found = await dashboards.get(found.id)
        await attachments.attach(session_id, AttachmentKind.DASHBOARD, str(found.id), actor)
        return found

    return (
        await dashboard(
            DOORS,
            [
                (definitions, 0, 0, 12, 3),
                (rates, 0, 3, 12, 6),
                (cancer_table, 0, 9, 6, 7),
                (site_map, 6, 9, 6, 7),
                (doors_table, 0, 16, 12, 8),
                (pending, 0, 24, 12, 7),
            ],
        ),
        await dashboard(NEAR_YOU, [(advice, 0, 0, 12, 3), (patient_table, 0, 3, 12, 10)]),
    )
