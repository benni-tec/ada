"""Dashboard integration on minimal contract rows until the registry seed is available."""

from types import SimpleNamespace

import pytest
from dishka import AsyncContainer

from ada.composition import create_container
from ada.config import Settings
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.trials.dashboards import DOORS, NEAR_YOU, create_dashboards
from factories import AGENT
from memory import memory_adapters

pytestmark = pytest.mark.anyio


async def test_dashboard_slots_load_and_reseeding_keeps_the_same_widgets(
    unreachable_settings: Settings,
) -> None:
    container: AsyncContainer = create_container(unreachable_settings, *memory_adapters())
    try:
        async with container() as request:
            project = await (await request.get(ProjectService)).create("Trial dashboard fixtures")
            session = await (await request.get(SessionService)).create(project.id, "Trials")
            pipelines = await request.get(PipelineService)
            # One wide row stands in for the contracted outputs, with real SQL execution,
            # widget validation, dashboard copies and data reads still in use.
            fields = {
                "nct_id": "'NCT1'",
                "title": "'Lung trial'",
                "url": "'https://example.test/trial'",
                "phase": "'PHASE2'",
                "cancer_groups": "'lung'",
                "sponsor": "'Sponsor'",
                "open_countries": "'Sweden'",
                "nearest_facility": "'Hospital'",
                "nearest_city": "'Stockholm'",
                "km_helsinki": "400.5",
                "km_kuopio": "600.2",
                "km_oulu": "700.1",
                "facility": "'Hospital'",
                "city": "'Stockholm'",
                "country": "'Sweden'",
                "sex": "'ALL'",
                "min_age_years": "18.0",
                "max_age_years": "NULL::DOUBLE",
                "eligibility": "'As written'",
                "status_fi": "'authorised, recruitment pending'",
                "recruiting_in": "'Sweden'",
                "decision_date": "DATE '2026-11-14'",
                "lat": "59.3",
                "lon": "18.1",
                "has_fi_site": "false",
                "registry": "'ClinicalTrials.gov'",
                "cancer_group": "'lung'",
                "trials": "1",
                "per_million": "0.1",
                "rate_ratio_fi": "0.5",
            }
            row = await pipelines.add_transform(
                project.id,
                "SELECT " + ", ".join(f"{value} AS {name}" for name, value in fields.items()),
                [],
                AGENT,
            )
            steps = SimpleNamespace(
                **dict.fromkeys(
                    ("trials", "trial_rates", "trial_doors", "case_trials", "ctis_finland_pending"),
                    row,
                )
            )
            first = await create_dashboards(request, project.id, session.id, steps, AGENT)
        async with container() as request:
            widgets = await request.get(WidgetService)
            before = {w.id for w in await widgets.list(project.id)}
            again = await create_dashboards(request, project.id, session.id, steps, AGENT)
            assert [d.id for d in first] == [d.id for d in again]
            assert {w.id for w in await widgets.list(project.id)} == before
            attachments = await (await request.get(AttachmentService)).list(session.id)
            assert {a.ref for a in attachments} == {str(d.id) for d in again}
            dashboards = await request.get(DashboardService)
            assert {d.name for d in await dashboards.list(project.id)} == {DOORS, NEAR_YOU}
            for dashboard, count in zip(again, (6, 2), strict=True):
                version = await dashboards.current(dashboard.id)
                assert version is not None
                assert len(version.slots) == count
                for slot in version.slots:
                    data = await widgets.data(slot.widget_id)
                    assert data.rows
    finally:
        await container.close()
