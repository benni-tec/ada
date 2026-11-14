"""Registry recordings through real HTTP readers, SQL pipelines and persisted runs."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope

from ada.adapters.clock import SystemClock
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.sessions import EntryKind
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.trials import seed
from ada.entrypoints.cli.trials.dashboards import DOORS, NEAR_YOU
from ada.entrypoints.cli.trials.seed import _build, seed_trials
from ada.entrypoints.cli.trials.sources import COUNTRIES
from memory import MemoryBackground

pytestmark = pytest.mark.anyio
RECORDINGS = Path(__file__).parent / "recordings" / "trials"


@pytest.fixture
async def container(migrated_database_url: str, tmp_path: Path) -> AsyncIterator[AsyncContainer]:
    def registry(request: httpx.Request) -> httpx.Response:
        if request.url.host == "clinicaltrials.gov":
            country = request.url.params["query.locn"]
            name = f"ctgov-{country}.json"
        else:
            assert request.method == "POST"
            body = json.loads(request.content)
            country = next(
                c for c, code in COUNTRIES.items() if body["searchCriteria"]["msc"] == [code]
            )
            name = f"ctis-{country}-p{body['pagination']['page']}.json"
        return httpx.Response(200, json=json.loads((RECORDINGS / name).read_text()))

    readers = HttpSourceReaders(create_client(httpx.MockTransport(registry)), SystemClock())
    outside = Provider(scope=Scope.APP)
    outside.provide(lambda: readers, provides=SourceReaders)
    result = create_container(
        Settings(
            database_url=migrated_database_url,
            valkey_url="redis://127.0.0.1:1/0",
            data_dir=tmp_path,
        ),
        MemoryBackground(),
        outside,
    )
    try:
        yield result
    finally:
        await result.close()


async def test_seed_is_idempotent_without_fetching(container: AsyncContainer) -> None:
    project_id = await seed_trials(container)
    async with container() as request:
        pipelines = await request.get(PipelineService)
        before = {
            o.id
            for p in await pipelines.pipelines(project_id)
            for o in await pipelines.lineage(p.operator_id)
        }
    assert await seed_trials(container) == project_id
    async with container() as request:
        sources = await (await request.get(SourceService)).list(project_id)
        assert len(sources) == 8
        assert all(s.last_checked_at is None for s in sources)
        sessions = await request.get(SessionService)
        [session] = await sessions.list(project_id)
        entries = await sessions.entries(session.id)
        assert {e.text.split(":")[0] for e in entries if e.kind == EntryKind.OPERATOR} == {
            "trials",
            "trial_sites",
            "trial_doors",
            "ctis_trials",
            "ctis_finland_pending",
            "trial_rates",
            "case_trials",
        }
        pipelines = await request.get(PipelineService)
        after = {
            o.id
            for p in await pipelines.pipelines(project_id)
            for o in await pipelines.lineage(p.operator_id)
        }
    assert before == after
    assert len(after) == 18


async def test_refresh_preserves_eligibility_sites_doors_and_ctis_pages(
    container: AsyncContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed, "REFRESH_DELAY_SECONDS", 0)
    project_id = await seed_trials(container, refresh=True)
    async with container() as request:
        sources = await (await request.get(SourceService)).list(project_id)
        built = await _build(request, project_id, {s.name: s.id for s in sources})
        runs = await request.get(RunService)
        [run] = await runs.list(project_id)
        doors = await runs.read(run.id, built.trial_doors.id)
        cases = await runs.read(run.id, built.case_trials.id)
        pending = await runs.read(run.id, built.ctis_finland_pending.id)
        ctis = await runs.read(run.id, built.ctis_trials.id)
        rates = await runs.read(run.id, built.trial_rates.id)

    def rows(data):  # noqa: ANN001, ANN202
        return [dict(zip([c.name for c in data.columns], row, strict=True)) for row in data.rows]

    door = next(r for r in rows(doors) if r["nct_id"] == "NCT07195695")
    assert 300 < door["km_helsinki"] < 1500
    assert all(r["min_age_years"] == 18 for r in rows(cases))
    assert "NCT05634889" not in {r["nct_id"] for r in rows(doors)}
    assert "2025-523366-24-00" in {r["ct_number"] for r in rows(pending)}
    page2 = json.loads((RECORDINGS / "ctis-Sweden-p2.json").read_text())["data"][0]["ctNumber"]
    assert page2 in {r["ct_number"] for r in rows(ctis)}
    assert all(r["eligibility"] and r["url"].endswith(r["nct_id"]) for r in rows(cases))
    assert any(r["country"] == "Finland" for r in rows(cases))

    fi_rate = next(
        r
        for r in rows(rates)
        if r["registry"] == "ClinicalTrials.gov"
        and r["cancer_group"] == "all"
        and r["country"] == "Finland"
    )
    assert fi_rate["trials"] == 2
    assert fi_rate["per_million"] == pytest.approx(2 / 5.64)

    async with container() as request:
        dashboards = await request.get(DashboardService)
        widgets = await request.get(WidgetService)
        first = {d.name: d.id for d in await dashboards.list(project_id)}
        assert set(first) == {DOORS, NEAR_YOU}
        before = {w.id for w in await widgets.list(project_id)}
        [session] = await (await request.get(SessionService)).list(project_id)
        attachments = await (await request.get(AttachmentService)).list(session.id)
        assert {a.ref for a in attachments} == {str(d) for d in first.values()}
        for name, dashboard_id in first.items():
            version = await dashboards.current(dashboard_id)
            assert version is not None
            assert len(version.slots) == (6 if name == DOORS else 2)
            for slot in version.slots:
                data = await widgets.data(slot.widget_id)
                assert data.rows
                widget = await widgets.get(slot.widget_id)
                columns = [c.name for c in data.columns]
                if widget.title == "Recruiting abroad, no Finnish site":
                    distances = [row[columns.index("km_helsinki")] for row in data.rows]
                    assert distances == sorted(distances, key=lambda d: (d is None, d or 0))
                if widget.title == "Recruiting cancer trials per million":
                    assert widget.spec["transform"] == [{"filter": "datum.cancer_group === 'all'"}]
                    assert any(row[columns.index("cancer_group")] == "all" for row in data.rows)

    assert await seed_trials(container) == project_id
    async with container() as request:
        assert {
            d.name: d.id for d in await (await request.get(DashboardService)).list(project_id)
        } == first
        assert {w.id for w in await (await request.get(WidgetService)).list(project_id)} == before
