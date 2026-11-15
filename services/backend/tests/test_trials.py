"""Registry recordings through real HTTP readers, SQL pipelines and persisted runs."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope

from ada.adapters.clock import SystemClock
from ada.adapters.memory.web import MemoryWebBudget
from ada.adapters.sources.http import HttpSourceReaders, create_client
from ada.composition import create_container
from ada.config import Settings
from ada.core.models.alerts import AlertState, Severity
from ada.core.models.base import Id
from ada.core.models.errors import Invalid
from ada.core.models.sessions import EntryKind
from ada.core.models.sources import CheckEvery
from ada.core.ports.repositories import DataSourceRepository
from ada.core.ports.sources import SourceCheckLog, SourceReaders
from ada.core.services.ports.alerts import AlertService
from ada.core.services.ports.attachments import AttachmentService
from ada.core.services.ports.dashboards import DashboardService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.core.services.ports.widgets import WidgetService
from ada.entrypoints.cli.trials import seed
from ada.entrypoints.cli.trials.dashboards import DOORS, NEAR_YOU
from ada.entrypoints.cli.trials.monitoring import (
    DASHBOARD,
    FINNISH_RULE,
    HOSPITAL_RULE,
    site_changes_sql,
)
from ada.entrypoints.cli.trials.pages import PAGES, page_options, study_page
from ada.entrypoints.cli.trials.seed import SEED, _build, register_trial_page, seed_trials
from ada.entrypoints.cli.trials.sources import COUNTRIES
from ada.entrypoints.cli.trials.steps import TRIAL_SITES
from memory import MemoryBackground, memory_adapters

pytestmark = pytest.mark.anyio
RECORDINGS = Path(__file__).parent / "recordings" / "trials"


@pytest.fixture
def finland_fixture() -> dict:
    return json.loads((RECORDINGS / "ctgov-Finland.json").read_text())


@pytest.fixture
def recorded_pages() -> dict[str, str]:
    return {
        p.address: "hus.md" if "hus.fi" in p.address else "fican-east.md"
        for p in PAGES
        if "hus.fi" in p.address or "itainen" in p.address
    }


@pytest.fixture(params=["memory", "postgres"])
async def container(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    finland_fixture: dict,
    recorded_pages: dict[str, str],
) -> AsyncIterator[AsyncContainer]:
    def registry(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/web/scrape":
            body = json.loads(request.content)
            url = body["url"]
            fixture = recorded_pages.get(url)
            if fixture == "REQUEST_TIMEOUT":
                raise Invalid("REQUEST_TIMEOUT")
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
        data = json.loads((RECORDINGS / name).read_text())
        if "studies" in data:
            # CT.gov synonym expansion can return non-cancer conditions.
            extra = json.loads(json.dumps(data["studies"][0]))
            protocol = extra["protocolSection"]
            protocol["identificationModule"]["nctId"] = "NCT_NON_CANCER"
            protocol["conditionsModule"]["conditions"] = ["Myasthenia Gravis"]
            data["studies"].append(extra)
            for study in data["studies"]:
                locations = study["protocolSection"]["contactsLocationsModule"]["locations"]
                locations.append(
                    dict(locations[0], status="NOT_YET_RECRUITING", city="Closed test site")
                )
        return httpx.Response(200, json=data)

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
    async with container() as request:
        projects = await request.get(ProjectService)
        project = await projects.get(project_id)
        assert project.agent_instructions == seed.AGENT_INSTRUCTIONS
        assert len(project.agent_instructions) < 900
        await projects.update(project_id, project.revision, agent_instructions="Old instructions")
        # Someone took the matcher off its case type: the reseed puts it back on one, running
        # on every save, as the instructions promise a result on every save.
        models = await request.get(StatisticalModelService)
        [matcher] = [m for m in await models.list(project_id) if m.kind == "trial_matcher"]
        case_type_id = matcher.case_type_id
        await models.set_case_type(matcher.id, None, False)
    assert await seed_trials(container) == project_id
    async with container() as request:
        assert (await (await request.get(ProjectService)).get(project_id)).agent_instructions == (
            seed.AGENT_INSTRUCTIONS
        )
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
            "county_cities",
            "trial_site_changes",
            "hospital_trials",
            "hospital_trial_gaps",
            "hospital_trial_changes",
            "sponsor_sites",
        }
        # The trial matcher runs on its own case type, once, reading the current steps.
        models = await (await request.get(StatisticalModelService)).list(project_id)
        [matcher] = [m for m in models if m.kind == "trial_matcher"]
        assert matcher.auto_run and matcher.latest_version == 1
        assert matcher.case_type_id == case_type_id
        pipelines = await request.get(PipelineService)
        after = {
            o.id
            for p in await pipelines.pipelines(project_id)
            for o in await pipelines.lineage(p.operator_id)
        }
    assert before == after
    assert len(after) > 15


async def test_refresh_survives_failed_hospital_page(
    container: AsyncContainer,
    recorded_pages: dict[str, str],
    finland_fixture: dict,
    capsys: pytest.CaptureFixture[str],
) -> None:
    page = PAGES[0]
    recorded_pages[page.address] = "REQUEST_TIMEOUT"
    finland_fixture["studies"][0]["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"][
        "name"
    ] = "Pfizer"
    finland_fixture["studies"][0]["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"] = {
        "date": "2026-11-15"
    }
    study = study_page("NCT05634889", "Pfizer")
    assert study is not None
    recorded_pages[study.address] = "REQUEST_TIMEOUT"
    project_id = await seed_trials(container, refresh=True)
    async with container() as request:
        assert (await (await request.get(ProjectService)).get(project_id)).id == project_id
        sources = await (await request.get(SourceService)).list(project_id)
        built = await _build(request, project_id, {s.name: s.id for s in sources})
        runs = await request.get(RunService)
        [run] = await runs.list(project_id)
        assert not (await runs.read(run.id, built.sponsor_sites.id)).rows
        dashboards = await (await request.get(DashboardService)).list(project_id)
        assert {DOORS, NEAR_YOU, DASHBOARD} <= {d.name for d in dashboards}
        assert len(await (await request.get(SessionService)).list(project_id)) == 1
        source = next(
            s
            for s in await (await request.get(SourceService)).list(project_id)
            if s.name == page.name
        )
        assert source.last_error == "REQUEST_TIMEOUT"
    output = capsys.readouterr().out
    assert f"  {page.name}: refresh failed (REQUEST_TIMEOUT)" in output
    assert (
        f"  2 web pages failed; rerun the seed to retry them: {page.name}, {study.name}" in output
    )


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
    assert all(r["nct_id"] != "NCT_NON_CANCER" for r in rows(cases))
    assert all(r["city"] != "Closed test site" for r in rows(cases))

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
                if name == NEAR_YOU and widget.type == "table":
                    assert widget.spec["columns"] == [
                        "city",
                        "km_helsinki",
                        "km_kuopio",
                        "km_oulu",
                        "title",
                        "eligibility",
                        "url",
                    ]
                    distances = [
                        min((d for d in row[1:4] if d is not None), default=None)
                        for row in data.rows
                    ]
                    assert distances == sorted(distances, key=lambda d: (d is None, d or 0))
                if widget.title == "Abroad, no Finnish site":
                    distances = [row[columns.index("km_helsinki")] for row in data.rows]
                    assert distances == sorted(distances, key=lambda d: (d is None, d or 0))
                if widget.title == "Recruiting trials per million":
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
    previous = next(
        t
        for t in finland_fixture["studies"]
        if t["protocolSection"]["identificationModule"]["nctId"] == "NCT07195695"
    )
    previous["protocolSection"]["contactsLocationsModule"]["locations"].append(
        {
            "facility": "HUS",
            "city": "Helsinki",
            "country": "Finland",
            "status": "NOT_YET_RECRUITING",
        }
    )
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
            "finnish_site_recruiting",
            "nordic_site_closed",
        }
        dashboard = next(
            d
            for d in await (await request.get(DashboardService)).list(project_id)
            if d.name == DASHBOARD
        )
        alerts = await request.get(AlertService)
        rules = await alerts.list_rules(dashboard.id)
        bulletin = next(r for r in rules if r.name == "Weekly trial-gap bulletin")
        assert bulletin.key_columns == ("registry", "cancer_group", "week")
        assert bulletin.check_interval_seconds == 7 * 86400
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
    assert {p.interval for p in PAGES} == {"10min", "hourly", "daily"}
    assert {page_options(p)["hospital"] for p in PAGES if p.interval == "10min"} == {
        "HUS",
        "KYS",
        "Tays",
    }
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


async def test_hospital_page_changes_and_alert(
    container: AsyncContainer,
    recorded_pages: dict[str, str],
) -> None:
    project_id = await seed_trials(container, refresh=True)
    hus = next(p for p in PAGES if "hus.fi" in p.address)
    async with container() as request:
        sources = await request.get(SourceService)
        registered = {s.name: s.id for s in await sources.list(project_id)}
        built = await _build(request, project_id, registered)
        runs = await request.get(RunService)
        run = await runs.start(project_id, SEED)
        assert not (await runs.read(run.id, built.hospital_trial_changes.id)).rows
    recorded_pages[hus.address] = "hus-new.md"
    async with container() as request:
        await (await request.get(SourceService)).refresh(registered[hus.name], force=True)
    async with container() as request:
        runs = await request.get(RunService)
        run = await runs.start(project_id, SEED)
        changes = await runs.read(run.id, built.hospital_trial_changes.id)
        names = [c.name for c in changes.columns]
        assert [
            (r[names.index("change_kind")], r[names.index("page")], r[names.index("trial_id")])
            for r in changes.rows
        ] == [("listed_by_hospital", hus.name, "NCT07195695")]
        dashboard = next(
            d
            for d in await (await request.get(DashboardService)).list(project_id)
            if d.name == DASHBOARD
        )
        alerts = await request.get(AlertService)
        rule = next(r for r in await alerts.list_rules(dashboard.id) if r.name == HOSPITAL_RULE)
        await alerts.check(rule.id)
        firing = [
            a for a in await alerts.alerts(project_id, AlertState.FIRING) if a.rule_id == rule.id
        ]
        assert [a.key for a in firing] == [{"page": hus.name, "trial_id": "NCT07195695"}]
    recorded_pages[hus.address] = "hus.md"
    async with container() as request:
        await (await request.get(SourceService)).refresh(registered[hus.name], force=True)
    async with container() as request:
        runs = await request.get(RunService)
        run = await runs.start(project_id, SEED)
        changes = await runs.read(run.id, built.hospital_trial_changes.id)
        assert [r[names.index("change_kind")] for r in changes.rows] == ["unlisted_by_hospital"]
        alerts = await request.get(AlertService)
        await alerts.check(rule.id)
        assert not [
            a for a in await alerts.alerts(project_id, AlertState.FIRING) if a.rule_id == rule.id
        ]


async def test_register_page_wires_unions_and_watches_all_pages(
    container: AsyncContainer,
    recorded_pages: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = await seed_trials(container, refresh=True)
    url = "https://hospital.example/trials"
    recorded_pages[url] = "hus-new.md"
    watched = []
    async with container() as request:
        settings = await request.get(Settings)
        monkeypatch.setattr(settings, "ada_public_url", "https://ada.example")
        source_service = await request.get(SourceService)

        async def watch(service, id, check_every=None):  # noqa: ANN001, ANN202
            watched.append((id, check_every))
            source = await service.get(id)
            await service.sources.set_monitor(
                id, f"monitor-{id}", "test-secret", source.freshness, check_every
            )
            return await service.get(id)

        monkeypatch.setattr(type(source_service), "watch", watch)
        alert_service = await request.get(AlertService)
        monitoring = next(
            d
            for d in await (await request.get(DashboardService)).list(project_id)
            if d.name == DASHBOARD
        )
        rule = next(
            r for r in await alert_service.list_rules(monitoring.id) if r.name == HOSPITAL_RULE
        )
        await alert_service.update_rule(rule.id, rule.revision, severity=Severity.CRITICAL)
        page = await register_trial_page(
            request, project_id, url, "New hospital", "hospital_list", "Finland"
        )
        assert page_options(page)["interval"] == "hourly"
        registered = {s.name: s.id for s in await source_service.list(project_id)}
        before = await _build(request, project_id, registered)
        assert (
            await register_trial_page(request, project_id, url, "Alias", "hospital_list", "Finland")
        ).id == page.id
        after = await _build(request, project_id, registered)
        assert after.hospital_trials.id == before.hospital_trials.id
        assert after.hospital_trial_changes.id == before.hospital_trial_changes.id
        study = await register_trial_page(
            request,
            project_id,
            "https://sponsor.example/study",
            "Research study",
            "sponsor_study_page",
            "Sweden",
        )
        assert page_options(study)["interval"] == "daily"
        all_sources = await source_service.list(project_id)
        assert sorted(watched) == sorted(
            (s.id, page_options(s)["interval"]) for s in all_sources if page_options(s)
        )
        hus = next(s for s in all_sources if page_options(s).get("hospital") == "HUS")
        await (await request.get(DataSourceRepository)).set_monitor(
            hus.id, "old-monitor", "test-secret", hus.freshness, CheckEvery.DAILY
        )
        watched.clear()
        dashboard = next(
            d
            for d in await (await request.get(DashboardService)).list(project_id)
            if d.name == DASHBOARD
        )
        rules = await (await request.get(AlertService)).list_rules(dashboard.id)
        [active] = [r for r in rules if r.name == HOSPITAL_RULE and r.enabled]
        assert active.severity == Severity.CRITICAL
        assert any(not r.enabled and r.name.startswith(HOSPITAL_RULE) for r in rules)
    await seed_trials(container)
    assert watched == [(hus.id, CheckEvery.TEN_MINUTES)]
    async with container() as request:
        sources = await request.get(SourceService)
        await sources.refresh(page.id)
        await sources.refresh(study.id)
    async with container() as request:
        sources = {s.name: s.id for s in await (await request.get(SourceService)).list(project_id)}
        built = await _build(request, project_id, sources)
        runs = await request.get(RunService)
        run = await runs.start(project_id, SEED)
        listed = await runs.read(run.id, built.hospital_trials.id)
        assert any(r[0] == "New hospital" for r in listed.rows)
        assert len((await runs.read(run.id, built.sponsor_sites.id)).rows) == 1


async def test_refresh_retries_failed_recent_sponsor_check(
    container: AsyncContainer, finland_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    finland_fixture["studies"][0]["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"][
        "name"
    ] = "Pfizer"
    finland_fixture["studies"][0]["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"] = {
        "date": "2026-11-15"
    }
    project_id = await seed_trials(container, refresh=True)
    async with container() as request:
        sources = await request.get(SourceService)
        study = next(
            s
            for s in await sources.list(project_id)
            if page_options(s).get("kind") == "sponsor_study_page"
        )
        await (await request.get(SourceCheckLog)).record_failure(
            study.id, datetime.now(UTC), study.last_probe_token, "temporary failure"
        )
        refresh = type(sources).refresh
        refreshed = []

        async def track_refresh(service, id, **kwargs):  # noqa: ANN001, ANN003, ANN202
            refreshed.append(id)
            return await refresh(service, id, **kwargs)

        monkeypatch.setattr(type(sources), "refresh", track_refresh)
    await seed_trials(container, refresh=True)
    assert study.id in refreshed


def test_site_changes_reconcile_sources_and_unnamed_sites() -> None:
    with duckdb.connect() as db:
        for i in range(4):
            db.execute(f"""
                CREATE TABLE input_{i} (
                    nct_id VARCHAR, title VARCHAR, last_update VARCHAR, locations JSON,
                    snapshot_at TIMESTAMP, snapshot_rank INTEGER
                )
            """)

        def observation(source: int, rank: int, statuses: list[str], trial: str = "NCT1") -> None:
            sites = [
                {"city": "Helsinki", "country": "Finland", "status": status} for status in statuses
            ]
            db.execute(
                f"INSERT INTO input_{source} VALUES (?, 'Trial', '2026-01-01', ?, ?, ?)",
                [trial, json.dumps(sites), f"2026-01-{4 - rank + source:02d}", rank],
            )

        observation(0, 2, ["recruiting", "COMPLETED"])
        observation(1, 1, ["RECRUITING", "COMPLETED", "RECRUITING"])
        sql = site_changes_sql(TRIAL_SITES)
        # Moving between country pulls, duplicate unnamed sites and casing are not changes.
        assert db.execute(sql).fetchall() == []

        observation(0, 1, ["RECRUITING"])
        observation(3, 1, ["COMPLETED"])
        db.execute("UPDATE input_0 SET last_update = '2026-02-01' WHERE snapshot_rank = 1")
        assert db.execute(sql).fetchall() == []
        # With matching registry revisions, the later fetch breaks the tie.
        db.execute("UPDATE input_3 SET last_update = '2026-02-01'")
        assert [row[0] for row in db.execute(sql).fetchall()] == ["nordic_site_closed"]
        db.execute("DELETE FROM input_3")
        db.execute("DELETE FROM input_0")
        observation(0, 2, ["not_yet_recruiting", "COMPLETED"])
        result = db.execute(sql)
        rows = [
            dict(zip([c[0] for c in result.description], row, strict=True))
            for row in result.fetchall()
        ]
        assert {r["change_kind"] for r in rows} == {"finnish_site_recruiting", "nordic_site_opened"}
        assert len(rows) == 2

        observation(2, 1, ["RECRUITING"], trial="NCT2")
        observation(3, 1, ["recruiting"], trial="NCT2")
        result = db.execute(sql)
        rows = [
            dict(zip([c[0] for c in result.description], row, strict=True))
            for row in result.fetchall()
        ]
        assert sum(r["change_kind"] == "new_trial" for r in rows) == 1

        observation(2, 1, ["not_yet_recruiting"], trial="NCT3")
        result = db.execute(sql)
        rows = [
            dict(zip([c[0] for c in result.description], row, strict=True))
            for row in result.fetchall()
        ]
        assert {r["change_kind"] for r in rows if r["nct_id"] == "NCT3"} == {
            "new_trial",
            "finnish_site_added",
        }


def test_site_changes_guard_truncated_sources() -> None:
    with duckdb.connect() as db:
        for source in range(4):
            db.execute(f"""
                CREATE TABLE input_{source} AS
                SELECT 'NCT' || i AS nct_id, 'Trial' AS title,
                    '2026-01-01' AS last_update,
                    '[{{"country":"Sweden","status":"RECRUITING"}}]'::JSON AS locations,
                    TIMESTAMP '2026-01-01' AS snapshot_at, 2 AS snapshot_rank
                FROM range({source * 10}, {source * 10 + 4}) t(i)
            """)
        sql = site_changes_sql(TRIAL_SITES)
        # Empty and truncated sources suppress removals; exactly half is valid.
        for source, count in ((1, 1), (2, 2), (3, 3)):
            db.execute(f"""
                INSERT INTO input_{source}
                SELECT nct_id, title, last_update, locations,
                    TIMESTAMP '2026-01-02', 1
                FROM input_{source} LIMIT {count}
            """)
        db.execute("""
            INSERT INTO input_1 VALUES ('NEW', 'New trial', '2026-01-02',
                '[{"country":"Sweden","status":"RECRUITING"}]', '2026-01-02', 1)
        """)
        # Keep this source below half even with the addition.
        db.execute("""
            INSERT INTO input_1 SELECT 'OLD', title, last_update, locations, snapshot_at, 2
            FROM input_1 LIMIT 1
        """)
        rows = db.execute(sql).fetchall()
        assert {(r[0], r[1]) for r in rows} == {
            ("trial_left_list", "NCT22"),
            ("nordic_site_closed", "NCT22"),
            ("trial_left_list", "NCT23"),
            ("nordic_site_closed", "NCT23"),
            ("trial_left_list", "NCT33"),
            ("nordic_site_closed", "NCT33"),
            ("new_trial", "NEW"),
            ("nordic_site_opened", "NEW"),
        }
