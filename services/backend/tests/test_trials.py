"""Registry recordings through real HTTP readers, SQL pipelines and persisted runs."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope

from ada.adapters.clock import SystemClock
from ada.adapters.memory.web import MemoryWebBudget
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState
from ada.core.models.base import Id
from ada.core.models.sessions import EntryKind
from ada.core.ports.sources import SourceReaders
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.trials import seed
from ada.entrypoints.cli.trials.dashboards import DOORS, NEAR_YOU
from ada.entrypoints.cli.trials.monitoring import DASHBOARD, FINNISH_RULE
from ada.entrypoints.cli.trials.pages import PAGES, study_page
from ada.entrypoints.cli.trials.seed import SEED, _build, seed_trials
from ada.entrypoints.cli.trials.sources import COUNTRIES
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio
RECORDINGS = Path(__file__).parent / "recordings" / "trials"


@pytest.fixture
def finland_fixture() -> dict:
    return json.loads((RECORDINGS / "ctgov-Finland.json").read_text())


@pytest.fixture(params=["memory", "postgres"])
async def container(
    request: pytest.FixtureRequest, tmp_path: Path, finland_fixture: dict
) -> AsyncIterator[AsyncContainer]:
    def registry(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/web/scrape":
            body = json.loads(request.content)
            url = body["url"]
            if "jsonParams" in body:
                return httpx.Response(
                    200,
                    json={
                        "json": {
                            "success": True,
                            "data": {
                                "rows": [
                                    {
                                        "nct_id": "NCT05634889",
                                        "overall_status": None,
                                        "facility": "HUS",
                                        "city": "Helsinki",
                                        "country": "Finland",
                                        "site_status": "Recruiting",
                                    }
                                ]
                            },
                        }
                    },
                )
            fixture = "hus.md" if "hus.fi" in url else "fican-east.md" if "itainen" in url else None
            markdown = (RECORDINGS / "pages" / fixture).read_text() if fixture else "No trial IDs"
            return httpx.Response(
                200,
                json={"url": url, "markdown": {"success": True, "data": markdown}, "metadata": {}},
            )
        if request.url.host == "clinicaltrials.gov":
            country = request.url.params["query.locn"]
            name = f"ctgov-{country}.json"
            if country == "Finland":
                return httpx.Response(200, json=finland_fixture)
        else:
            assert request.method == "POST"
            body = json.loads(request.content)
            country = next(
                c for c, code in COUNTRIES.items() if body["searchCriteria"]["msc"] == [code]
            )
            name = f"ctis-{country}-p{body['pagination']['page']}.json"
        return httpx.Response(200, json=json.loads((RECORDINGS / name).read_text()))

    readers = HttpSourceReaders(
        create_client(httpx.MockTransport(registry)),
        SystemClock(),
        allow_private=True,
        context_dev_key="test-key",
        web_budget=MemoryWebBudget(),
        web_daily_credit_limit=2000,
    )
    outside = Provider(scope=Scope.APP)
    outside.provide(lambda: readers, provides=SourceReaders)
    database_url = (
        request.getfixturevalue("migrated_database_url")
        if request.param == "postgres"
        else "postgresql+psycopg://test@127.0.0.1:1/test"
    )
    result = create_container(
        Settings(
            database_url=database_url,
            valkey_url="redis://127.0.0.1:1/0",
            data_dir=tmp_path,
        ),
        *(memory_adapters() if request.param == "memory" else (MemoryBackground(),)),
        outside,
    )
    try:
        yield result
    finally:
        await result.close()


@pytest.fixture(autouse=True)
def no_refresh_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "REFRESH_DELAY_SECONDS", 0)
    monkeypatch.setattr(seed, "WEB_REFRESHES_PER_MINUTE", 1e12)


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
        assert len(sources) == 8 + len(PAGES)
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
            "trial_site_changes",
            "hospital_trials",
            "hospital_trial_gaps",
            "sponsor_sites",
        }
        pipelines = await request.get(PipelineService)
        after = {
            o.id
            for p in await pipelines.pipelines(project_id)
            for o in await pipelines.lineage(p.operator_id)
        }
    assert before == after
    assert len(after) > 15


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
        assert set(first) == {DOORS, NEAR_YOU, DASHBOARD}
        before = {w.id for w in await widgets.list(project_id)}
        [session] = await (await request.get(SessionService)).list(project_id)
        attachments = await (await request.get(AttachmentService)).list(session.id)
        assert {a.ref for a in attachments} == {str(d) for d in first.values()}
        for name in (DOORS, NEAR_YOU):
            dashboard_id = first[name]
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


async def simulate_site_change(container: AsyncContainer, finland_fixture: dict) -> Id:
    """Seed recordings, then refresh Finland after changing the transport's mutable fixture."""
    # Copy the door trial from Sweden into Finland's next country listing.
    sweden = json.loads((RECORDINGS / "ctgov-Sweden.json").read_text())
    trial = next(
        t
        for t in sweden["studies"]
        if t["protocolSection"]["identificationModule"]["nctId"] == "NCT07195695"
    )
    if not any(
        t["protocolSection"]["identificationModule"]["nctId"] == "NCT07195695"
        for t in finland_fixture["studies"]
    ):
        finland_fixture["studies"].append(json.loads(json.dumps(trial)))
    project_id = await seed_trials(container, refresh=True)
    section = trial["protocolSection"]
    locations = section["contactsLocationsModule"]["locations"]
    closing = next(
        s for s in locations if s["country"] in COUNTRIES and s.get("status") == "RECRUITING"
    )
    closing["status"] = "COMPLETED"
    locations.append(
        {"facility": "HUS", "city": "Helsinki", "country": "Finland", "status": "RECRUITING"}
    )
    finland_fixture["studies"] = [
        t
        for t in finland_fixture["studies"]
        if t["protocolSection"]["identificationModule"]["nctId"] != "NCT07195695"
    ] + [trial]
    async with container() as request:
        sources = await (await request.get(SourceService)).list(project_id)
        source = next(s for s in sources if s.name == "ClinicalTrials.gov: Finland")
        await (await request.get(SourceService)).refresh(source.id, force=True)
    return project_id


async def test_monitoring_changes_and_finnish_alert(
    container: AsyncContainer, finland_fixture: dict
) -> None:
    # The Finland recording also carries the door trial as an old observation.
    sweden = json.loads((RECORDINGS / "ctgov-Sweden.json").read_text())
    trial = next(
        t
        for t in sweden["studies"]
        if t["protocolSection"]["identificationModule"]["nctId"] == "NCT07195695"
    )
    finland_fixture["studies"].append(trial)
    project_id = await seed_trials(container, refresh=True)
    async with container() as request:
        widget = next(
            w
            for w in await (await request.get(WidgetService)).list(project_id)
            if w.title == "trial_site_changes" and w.copied_from is None
        )
        run = await (await request.get(RunService)).start(project_id, SEED)
        assert not (await (await request.get(RunService)).read(run.id, widget.operator_id)).rows
    project_id = await simulate_site_change(container, finland_fixture)
    async with container() as request:
        runs = await request.get(RunService)
        run = await runs.start(project_id, SEED)
        data = await runs.read(run.id, widget.operator_id)
        rows = [dict(zip([c.name for c in data.columns], row, strict=True)) for row in data.rows]
        assert {r["change_kind"] for r in rows if r["nct_id"] == "NCT07195695"} >= {
            "finnish_site_added",
            "nordic_site_closed",
        }
        dashboard = next(
            d
            for d in await (await request.get(DashboardService)).list(project_id)
            if d.name == DASHBOARD
        )
        alerts = await request.get(AlertService)
        rules = await alerts.list_rules(dashboard.id)
        rule = next(r for r in rules if r.name == FINNISH_RULE)
        await alerts.check(rule.id)
        firing = [
            a for a in await alerts.alerts(project_id, AlertState.FIRING) if a.rule_id == rule.id
        ]
        assert len(firing) == 1
        assert "NCT07195695" in str((await alerts.rows(firing[0].id)).rows)


async def test_hospital_markdown_and_gaps(container: AsyncContainer, finland_fixture: dict) -> None:
    finland_fixture["studies"][0]["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"][
        "name"
    ] = "Pfizer"
    finland_fixture["studies"][0]["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"] = {
        "date": "2026-11-15"
    }
    project_id = await seed_trials(container, refresh=True)
    async with container() as request:
        sources = await (await request.get(SourceService)).list(project_id)
        built = await _build(request, project_id, {s.name: s.id for s in sources})
        runs = await request.get(RunService)
        [run] = await runs.list(project_id)
        listed = await runs.read(run.id, built.hospital_trials.id)
        gaps = await runs.read(run.id, built.hospital_trial_gaps.id)
        sponsor_sites = await runs.read(run.id, built.sponsor_sites.id)
        assert len(sponsor_sites.rows) == 1
        study = next(s for s in sources if s.name == "Sponsor study: NCT05634889")
        assert study.provenance is not None and study.provenance.extracted_by_model
    names = [c.name for c in listed.columns]
    rows = [dict(zip(names, row, strict=True)) for row in listed.rows]
    assert any(r["hospital"] == "KYS" and r["trial_id"] == "NCT06217822" for r in rows)
    assert any(
        r["hospital"] == "HUS" and r["section"] == "ALL (AKUUTTI LYMFOBLASTILEUKEMIA)" for r in rows
    )
    gap_names = [c.name for c in gaps.columns]
    assert any(
        row[gap_names.index("gap_kind")] == "hospital_only"
        and row[gap_names.index("nct_id")] == "NCT06217822"
        for row in gaps.rows
    )


def test_sponsor_page_patterns() -> None:
    for sponsor, host in (
        ("AstraZeneca", "astrazeneca"),
        ("Merck Sharp & Dohme LLC", "merck"),
        ("MSD", "merck"),
        ("Pfizer", "pfizer"),
    ):
        page = study_page("NCT06217822", sponsor)
        assert page is not None and host in page.address
        assert page.options["operation"] == "extract"
        assert page.freshness.ttl_seconds == 7 * 86400
    assert study_page("NCT06217822", "Merck KGaA") is None
    assert study_page("bad/id", "Pfizer") is None
