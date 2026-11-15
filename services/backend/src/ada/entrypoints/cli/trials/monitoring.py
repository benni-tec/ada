"""Snapshot changes and scrape-only hospital trial lists, with dashboard alert rules."""

from typing import TYPE_CHECKING

from dishka import AsyncContainer

from ada.adapters.sources.examples import DAY
from ada.config import Settings
from ada.core.models.actors import Actor
from ada.core.models.alerts import Severity
from ada.core.models.attachments import AttachmentKind
from ada.core.models.base import Id, JsonObject
from ada.core.models.dashboards import Dashboard, Slot
from ada.core.models.sources import CheckEvery
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.trials.pages import page_options

if TYPE_CHECKING:
    from ada.entrypoints.cli.trials.seed import TrialSteps

DASHBOARD = "Trial site monitoring"
MIN_SNAPSHOT_TRIAL_RATIO = 0.5
FINNISH_RULE = "A Finnish site opened on a Nordic cancer trial"
HOSPITAL_RULE = "A Finnish hospital page listed a new cancer trial"


def site_changes_sql(site_sql: str) -> str:
    """Compare reconciled Nordic snapshots using the seed's site parser.

    Empty history snapshots emit no rows, so an empty rank 2 cannot be distinguished
    from missing history and cannot establish a comparison baseline.
    """

    def sites(rank: int) -> str:
        sql = site_sql
        for i in range(4):
            sql = sql.replace(
                f"input_{i}",
                f"(SELECT * FROM observations WHERE snapshot_rank = {rank}"
                + (" AND false" if i else "")
                + ")",
            )
        return sql

    return f"""
WITH history AS (
    {" UNION ALL ".join(f"SELECT *, {i} AS source_index FROM input_{i}" for i in range(4))}
), guarded_sources AS (
    SELECT source_index FROM history GROUP BY source_index
    HAVING count(DISTINCT nct_id) FILTER (WHERE snapshot_rank = 1)
        < {MIN_SNAPSHOT_TRIAL_RATIO} * count(DISTINCT nct_id) FILTER (WHERE snapshot_rank = 2)
), observations AS (
    SELECT * FROM history
    QUALIFY row_number() OVER (PARTITION BY snapshot_rank, nct_id
        ORDER BY last_update DESC NULLS LAST, snapshot_at DESC, locations::VARCHAR DESC) = 1
), parsed_sites AS (
    SELECT *, 1 AS snapshot_rank FROM ({sites(1)})
    UNION ALL
    SELECT *, 2 AS snapshot_rank FROM ({sites(2)})
), sites AS (
    SELECT DISTINCT nct_id, coalesce(facility, '') AS facility, city, country, snapshot_rank,
        CASE WHEN bool_or(upper(site_status) = 'RECRUITING') THEN 'RECRUITING'
            ELSE max(upper(site_status)) END AS site_status
    FROM parsed_sites
    GROUP BY nct_id, coalesce(facility, ''), city, country, snapshot_rank
), new_sites AS (SELECT * FROM sites WHERE snapshot_rank = 1),
old_sites AS (SELECT * FROM sites WHERE snapshot_rank = 2),
new_trials AS (SELECT nct_id, title FROM observations WHERE snapshot_rank = 1),
old_trials AS (SELECT nct_id, title FROM observations WHERE snapshot_rank = 2),
site_pairs AS (
    SELECT coalesce(n.nct_id, o.nct_id) AS nct_id,
        coalesce(n.facility, o.facility) AS facility, coalesce(n.city, o.city) AS city,
        coalesce(n.country, o.country) AS country,
        o.site_status AS previous_status, n.site_status AS status,
        o.nct_id IS NULL AS added
    FROM new_sites n FULL OUTER JOIN old_sites o
    ON n.nct_id = o.nct_id AND n.facility IS NOT DISTINCT FROM o.facility
        AND n.city IS NOT DISTINCT FROM o.city AND n.country IS NOT DISTINCT FROM o.country
), events AS (
    SELECT 'new_trial' AS change_kind, n.nct_id, n.title,
        NULL::VARCHAR AS facility, NULL::VARCHAR AS city, NULL::VARCHAR AS country,
        NULL::VARCHAR AS previous_status, NULL::VARCHAR AS status
    FROM new_trials n ANTI JOIN old_trials o USING (nct_id)
    UNION ALL
    SELECT 'trial_left_list', o.nct_id, o.title, NULL, NULL, NULL, NULL, NULL
    FROM old_trials o ANTI JOIN new_trials n USING (nct_id)
    UNION ALL
    SELECT kind, p.nct_id, coalesce(n.title, o.title), facility, city, country,
        previous_status, status
    FROM site_pairs p LEFT JOIN new_trials n USING (nct_id)
    LEFT JOIN old_trials o USING (nct_id)
    CROSS JOIN (VALUES ('finnish_site_added'), ('finnish_site_recruiting'), ('nordic_site_opened'),
        ('nordic_site_closed')) kinds(kind)
    WHERE (kind = 'finnish_site_added' AND country = 'Finland' AND added
            AND status IS DISTINCT FROM 'RECRUITING')
        OR (kind = 'finnish_site_recruiting' AND country = 'Finland'
            AND status = 'RECRUITING' AND previous_status IS DISTINCT FROM 'RECRUITING')
        OR (country IN ('Finland', 'Sweden', 'Norway', 'Denmark') AND (
            (kind = 'nordic_site_opened' AND status = 'RECRUITING'
                AND previous_status IS DISTINCT FROM 'RECRUITING')
            OR (kind = 'nordic_site_closed' AND previous_status = 'RECRUITING'
                AND status IS DISTINCT FROM 'RECRUITING')))
)
SELECT DISTINCT e.*, (SELECT max(snapshot_at) FROM history WHERE snapshot_rank = 1)
    AS snapshot_at, 'https://clinicaltrials.gov/study/' || e.nct_id AS url,
    EXISTS (SELECT 1 FROM new_sites s WHERE s.nct_id = e.nct_id AND s.country = 'Finland')
        AS has_fi_site
FROM events e
WHERE EXISTS (SELECT 1 FROM history WHERE snapshot_rank = 2)
    AND (e.change_kind NOT IN ('trial_left_list', 'nordic_site_closed') OR NOT EXISTS (
        SELECT 1 FROM history h JOIN guarded_sources g USING (source_index)
        WHERE h.snapshot_rank = 2 AND h.nct_id = e.nct_id
    ))
"""


def _compare(column: str, value: str | int | bool, tag: str, op: str = "=") -> JsonObject:
    return {
        "id": tag,
        "kind": "compare",
        "op": op,
        "args": [
            {"id": f"{tag}_column", "kind": "column", "column": column},
            {"id": f"{tag}_value", "kind": "constant", "value": value},
        ],
    }


async def create_monitoring(
    request: AsyncContainer,
    project_id: Id,
    session_id: Id,
    sources: dict[str, Id],
    steps: TrialSteps,
    actor: Actor,
) -> Dashboard:
    from ada.entrypoints.cli.trials.sources import CTGOV
    from ada.entrypoints.cli.trials.steps import TRIAL_SITES

    pipelines = await request.get(PipelineService)
    widgets = await request.get(WidgetService)
    dashboards = await request.get(DashboardService)
    alerts = await request.get(AlertService)
    source_service = await request.get(SourceService)
    existing = {
        (w.operator_id, w.title): w for w in await widgets.list(project_id) if w.copied_from is None
    }
    histories = [
        await pipelines.add_history(project_id, sources[source.name], actor, last=2)
        for source in CTGOV
    ]
    trial_site_changes = await pipelines.add_transform(
        project_id, site_changes_sql(TRIAL_SITES), [h.id for h in histories], actor
    )
    weekly_rates = await pipelines.add_transform(
        project_id,
        "SELECT *, strftime(current_date, '%G-W%V') AS week FROM input_0",
        [steps.trial_rates.id],
        actor,
    )
    sessions = await request.get(SessionService)
    if not any(e.ref == trial_site_changes.id for e in await sessions.entries(session_id)):
        await sessions.record_operator(
            session_id,
            trial_site_changes.id,
            "trial_site_changes: latest two registry snapshots",
            actor,
        )
    tables = []

    async def table(operator_id: str, title: str) -> None:
        found = existing.get((operator_id, title))
        if found is None:
            found = await widgets.create(
                project_id, operator_id, "table", title, actor, session_id=session_id
            )
        tables.append(found)

    await table(trial_site_changes.id, "trial_site_changes")
    registered = {s.name: s for s in await source_service.list(project_id)}
    await table(steps.hospital_trial_changes.id, "hospital_trial_changes")
    await table(steps.hospital_trials.id, "hospital_trials")
    await table(steps.hospital_trial_gaps.id, "hospital_trial_gaps")
    await table(steps.sponsor_sites.id, "sponsor_sites [model-extracted]")
    for source in registered.values():
        metadata = page_options(source)
        if not metadata:
            continue
        if (await request.get(Settings)).ada_public_url:
            interval = CheckEvery(metadata["interval"])
            if source.monitor_id is None or source.check_every != interval:
                try:
                    await source_service.watch(source.id, check_every=interval)
                except Exception as error:
                    print(f"  {source.name}: watch failed ({type(error).__name__}); TTL refresh")
                else:
                    print(f"  watching {source.name}")
        else:
            print(f"  {source.name}: TTL refresh (ADA_PUBLIC_URL is not configured)")
    dashboard = next((d for d in await dashboards.list(project_id) if d.name == DASHBOARD), None)
    if dashboard is None:
        dashboard = await dashboards.create(project_id, DASHBOARD, actor)
    current = await dashboards.current(dashboard.id)
    current_widgets = [await widgets.get(s.widget_id) for s in current.slots] if current else []
    if current is None or [(w.operator_id, w.title) for w in current_widgets] != [
        (w.operator_id, w.title) for w in tables
    ]:
        await dashboards.edit(
            dashboard.id,
            [
                Slot(name=w.title, widget_id=w.id, layout={"x": 0, "y": i * 7, "w": 12, "h": 7})
                for i, w in enumerate(tables)
            ],
            dashboard.revision,
            actor,
        )
        dashboard = await dashboards.get(dashboard.id)
    await (await request.get(AttachmentService)).attach(
        session_id, AttachmentKind.DASHBOARD, str(dashboard.id), actor
    )
    rules = (
        (
            HOSPITAL_RULE,
            steps.hospital_trial_changes,
            _compare("change_kind", "listed_by_hospital", "hospital_listed"),
            ["page", "trial_id"],
            Severity.INFO,
            None,
        ),
        (
            FINNISH_RULE,
            trial_site_changes,
            _compare("change_kind", "finnish_site_recruiting", "fi"),
            ["nct_id", "facility"],
            Severity.WARNING,
            None,
        ),
        (
            "A Nordic site of a door trial opened or closed",
            trial_site_changes,
            {
                "id": "door",
                "kind": "and",
                "args": [
                    _compare("has_fi_site", False, "no_fi"),
                    {
                        "id": "changed",
                        "kind": "or",
                        "args": [
                            _compare("change_kind", "nordic_site_opened", "opened"),
                            _compare("change_kind", "nordic_site_closed", "closed"),
                        ],
                    },
                ],
            },
            ["nct_id", "facility", "change_kind"],
            Severity.INFO,
            None,
        ),
        (
            "New recruiting cancer trial in the Nordics",
            trial_site_changes,
            _compare("change_kind", "new_trial", "new"),
            ["nct_id"],
            Severity.INFO,
            None,
        ),
        (
            "Weekly trial-gap bulletin",
            weekly_rates,
            {
                "id": "gap",
                "kind": "and",
                "args": [
                    _compare("country", "SE+NO+DK", "pooled"),
                    _compare("rate_ratio_fi", 1, "ratio", "<"),
                ],
            },
            ["registry", "cancer_group", "week"],
            Severity.INFO,
            7 * DAY,
        ),
    )
    existing_rules = {r.name: r for r in await alerts.list_rules(dashboard.id)}
    # Rules cannot change their measure operator; retain the old rule as disabled history.
    hospital_rule = existing_rules.get(HOSPITAL_RULE)
    if hospital_rule is not None and hospital_rule.operator_id != steps.hospital_trial_changes.id:
        await alerts.update_rule(
            hospital_rule.id,
            hospital_rule.revision,
            name=f"{HOSPITAL_RULE} (superseded {hospital_rule.id})",
            enabled=False,
        )
        del existing_rules[HOSPITAL_RULE]
    for name, operator, formula, keys, severity, interval in rules:
        if name not in existing_rules:
            await alerts.create_rule(
                dashboard.id,
                name,
                operator.id,
                formula,
                keys,
                severity=severity,
                check_interval_seconds=interval,
            )
    return dashboard
