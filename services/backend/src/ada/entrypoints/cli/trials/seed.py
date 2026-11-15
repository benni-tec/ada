"""Idempotent registry project and SQL steps, following the waiting-times seed."""

import asyncio
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta

from dishka import AsyncContainer

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id
from ada.core.models.dashboards import Dashboard
from ada.core.models.errors import Invalid
from ada.core.models.operators import Operator
from ada.core.models.schema import MeasureRole, Roles
from ada.core.models.sources import DataSource, Provenance
from ada.core.ports.repositories import SnapshotRepository
from ada.core.services.pipelines.schemas import SOURCE_KEY
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.entrypoints.cli.trials import steps
from ada.entrypoints.cli.trials.dashboards import create_dashboards
from ada.entrypoints.cli.trials.monitoring import create_monitoring
from ada.entrypoints.cli.trials.pages import (
    EMPTY_SITES,
    HOSPITAL_TRIAL_GAPS,
    MAX_STUDY_PAGES,
    PAGES,
    WEB_REFRESHES_PER_MINUTE,
    PageKind,
    hospital_page,
    hospital_trial_changes_sql,
    hospital_trials_sql,
    page_options,
    sponsor_page,
    study_page,
)
from ada.entrypoints.cli.trials.sources import CTGOV, CTIS, SOURCES

PROJECT = "Nordic cancer trials"
AGENT_INSTRUCTIONS = (
    "Answer patient questions from case_trials. List only sites whose status is exactly "
    "RECRUITING. Give each site's city and the km column for the patient's city when it is "
    "Helsinki, Kuopio or Oulu, otherwise the nearest of the three, naming it. Quote each "
    "trial's eligibility text as written, never shortened into a verdict. Never filter or "
    "judge by age, sex, stage or any other eligibility criterion. Never say a patient "
    "qualifies or is accepted. Do not rank by efficacy or make promises. Sort by distance "
    "only. End every patient answer by saying to take the list to their oncologist, who "
    "decides eligibility."
)
SESSION = "Nordic cancer trials"
SEED = Actor(kind=ActorKind.SYSTEM, name="ada seed-trials")
REFRESH_DELAY_SECONDS = 1


@dataclass
class TrialSteps:
    trials: Operator
    trial_sites: Operator
    trial_doors: Operator
    ctis_trials: Operator
    ctis_finland_pending: Operator
    trial_rates: Operator
    case_trials: Operator
    hospital_trials: Operator
    hospital_trial_gaps: Operator
    sponsor_sites: Operator
    hospital_trial_changes: Operator


async def seed_trials(container: AsyncContainer, refresh: bool = False) -> Id:
    async with container() as request:
        projects = await request.get(ProjectService)
        sources = await request.get(SourceService)
        project = next((p for p in await projects.list() if p.name == PROJECT), None)
        if project is None:
            project = await projects.create(PROJECT)
        await projects.update(project.id, project.revision, agent_instructions=AGENT_INSTRUCTIONS)
        registered = {s.name: s.id for s in await sources.list(project.id)}
        for source in SOURCES:
            if source.name not in registered:
                ctgov = source in CTGOV
                saved = await sources.register(
                    project.id,
                    **source.registration(),
                    provenance=Provenance(
                        publisher="U.S. National Library of Medicine"
                        if ctgov
                        else "European Medicines Agency",
                        landing_page="https://clinicaltrials.gov"
                        if ctgov
                        else "https://euclinicaltrials.eu",
                        licence="unknown",
                        note="Registry submissions; reuse terms have not been verified.",
                    ),
                )
                registered[source.name] = saved.id
        for page in PAGES:
            if page.name not in registered:
                saved = await sources.register(project.id, **page.registration())
                registered[page.name] = saved.id
            else:
                saved = await sources.get(registered[page.name])
                if saved.address != page.address:
                    # Move the former English Pirha source without leaving a duplicate monitor.
                    if saved.monitor_id is not None:
                        saved = await sources.unwatch(saved.id)
                    saved = await sources.update(saved.id, saved.revision, address=page.address)
                if saved.options != page.options:
                    await sources.update(saved.id, saved.revision, options=page.options)
        project_id = project.id
    async with container() as request:
        built = await _build(request, project_id, registered)
    async with container() as request:
        web_sources = [
            s for s in await (await request.get(SourceService)).list(project_id) if page_options(s)
        ]
    study_names = sorted(
        s.name for s in web_sources if page_options(s)["kind"] == "sponsor_study_page"
    )
    hospital_names = sorted(
        s.name for s in web_sources if page_options(s)["kind"] == "hospital_list"
    )
    failures: list[str] = []
    if refresh:
        for index, source in enumerate(SOURCES):
            if index:
                await asyncio.sleep(REFRESH_DELAY_SECONDS)
            async with container() as request:
                await (await request.get(SourceService)).refresh(
                    registered[source.name], force=True
                )

        # Registry reads have no web inputs. Discover study pages before reading web steps.
        async with container() as request:
            runs = await request.get(RunService)
            run = await runs.start(project_id, SEED)
            candidates_step = await (await request.get(PipelineService)).add_transform(
                project_id,
                "SELECT nct_id, sponsor FROM input_0 WHERE fi_recruiting "
                "UNION SELECT nct_id, sponsor FROM input_1",
                [built.trials.id, built.trial_doors.id],
                SEED,
            )
            candidates = await runs.query(
                run.id,
                candidates_step.id,
                "SELECT * FROM input_0 ORDER BY nct_id",
                10000,
            )
            sources = await request.get(SourceService)
            for nct_id, sponsor in candidates.rows:
                page = study_page(nct_id, sponsor or "")
                if page is None or page.name in registered or len(study_names) >= MAX_STUDY_PAGES:
                    continue
                saved = await sources.register(project_id, **page.registration())
                registered[page.name] = saved.id
                study_names.append(page.name)
        web_names = hospital_names + sorted(study_names)
        for index, name in enumerate(web_names):
            if index:
                await asyncio.sleep(60 / WEB_REFRESHES_PER_MINUTE)
            async with container() as request:
                sources = await request.get(SourceService)
                source = await sources.get(registered[name])
                if (
                    name in study_names
                    and source.last_error is None
                    and source.last_checked_at is not None
                ):
                    if datetime.now(UTC) - source.last_checked_at < timedelta(days=7):
                        continue
                try:
                    await sources.refresh(source.id, force=True)
                except Exception as error:
                    if (
                        isinstance(error, Invalid)
                        and name in study_names
                        and "is fetched at most every" in str(error)
                    ):
                        print(f"  {name}: kept the recent snapshot ({error})")
                    else:
                        print(f"  {name}: refresh failed ({error})")
                        failures.append(name)
        async with container() as request:
            built = await _build(request, project_id, registered)
            for field in fields(built):
                try:
                    data = await (await request.get(RunService)).query(
                        run.id,
                        getattr(built, field.name).id,
                        "SELECT count(*) AS rows FROM input_0",
                        1,
                    )
                except Exception as error:
                    # A page that never had a snapshot fails every step that reads it.
                    print(f"  {field.name}: unavailable ({error})")
                    continue
                print(f"  {field.name}: {data.rows[0][0]} rows")
    async with container() as request:
        dashboards = await _publish(request, project_id, registered, built)
    print(
        f"  pages: {len(hospital_names)} hospital, {len(study_names)} study; "
        f"full web refresh estimate: {len(hospital_names) + 5 * len(study_names)} credits "
        "(1/scrape, about 5/extract; fresh snapshots are reused)"
    )
    print(f"Project {PROJECT!r}: {project_id}")
    for dashboard in dashboards:
        print(f"  dashboard {dashboard.id}  {dashboard.name}")
    if failures:
        print(
            f"  {len(failures)} web pages failed; rerun the seed to retry them: "
            f"{', '.join(failures)}"
        )
    return project_id


async def _build(request: AsyncContainer, project_id: Id, sources: dict[str, Id]) -> TrialSteps:
    pipelines = await request.get(PipelineService)
    ctgov = [await pipelines.add_source(project_id, sources[s.name], SEED) for s in CTGOV]
    ctis = [await pipelines.add_source(project_id, sources[s.name], SEED) for s in CTIS]

    async def transform(sql: str, inputs: list[Operator], roles: Roles | None = None) -> Operator:
        return await pipelines.add_transform(
            project_id, sql, [i.id for i in inputs], SEED, roles=roles
        )

    trials = await transform(steps.TRIALS, ctgov)
    sites = await transform(steps.TRIAL_SITES, ctgov)
    doors = await transform(steps.TRIAL_DOORS, [trials, sites])
    ctis_trials = await transform(steps.CTIS_TRIALS, ctis)
    pending = await transform(steps.CTIS_FINLAND_PENDING, [ctis_trials])
    rates = await transform(
        steps.TRIAL_RATES,
        [trials, sites, ctis_trials],
        Roles(measures=(MeasureRole(value="per_million"),)),
    )
    cases = await transform(steps.CASE_TRIALS, [trials, sites])
    registered_pages = sorted(
        await (await request.get(SourceService)).list(project_id), key=lambda s: s.name
    )
    hospitals = [s for s in registered_pages if page_options(s).get("kind") == "hospital_list"]
    pages = [await pipelines.add_source(project_id, s.id, SEED) for s in hospitals]
    hospital_trials = await transform(hospital_trials_sql(hospitals), pages)
    changes = []
    for source in hospitals:
        if page_options(source)["country"] != "Finland":
            continue
        history = await pipelines.add_history(project_id, source.id, SEED, last=2)
        changes.append(await transform(hospital_trial_changes_sql(source), [history]))
    hospital_changes = await transform(
        " UNION ALL ".join(f"SELECT * FROM input_{i}" for i in range(len(changes))), changes
    )
    gaps = await transform(HOSPITAL_TRIAL_GAPS, [hospital_trials, trials, sites])
    snapshots = await request.get(SnapshotRepository)
    sponsor_inputs = []
    for source in registered_pages:
        if page_options(source).get("kind") != "sponsor_study_page":
            continue
        operator = await pipelines.add_source(project_id, source.id, SEED)
        # A page that failed before its first snapshot (a removed study page) would fail
        # the whole union, so it stays out until a seed refresh reads it.
        if source.last_error is not None and (
            await snapshots.current(operator.id, SOURCE_KEY) is None
        ):
            continue
        sponsor_inputs.append(operator)
    sponsor_sites = await transform(
        " UNION ALL ".join(f"SELECT * FROM input_{i}" for i in range(len(sponsor_inputs)))
        if sponsor_inputs
        else EMPTY_SITES,
        sponsor_inputs,
    )
    return TrialSteps(
        trials,
        sites,
        doors,
        ctis_trials,
        pending,
        rates,
        cases,
        hospital_trials,
        gaps,
        sponsor_sites,
        hospital_changes,
    )


async def _publish(
    request: AsyncContainer,
    project_id: Id,
    registered: dict[str, Id],
    built: TrialSteps,
) -> tuple[Dashboard, Dashboard]:
    sessions = await request.get(SessionService)
    session = next((s for s in await sessions.list(project_id) if s.title == SESSION), None)
    if session is None:
        session = await sessions.create(project_id, SESSION)
    entries = {e.ref for e in await sessions.entries(session.id)}
    for field in fields(built):
        operator = getattr(built, field.name)
        if operator.id not in entries:
            await sessions.record_operator(
                session.id, operator.id, f"{field.name}: trial source data", SEED
            )
    dashboards = await create_dashboards(request, project_id, session.id, built, SEED)
    await create_monitoring(request, project_id, session.id, registered, built, SEED)
    return dashboards


async def register_trial_page(
    request: AsyncContainer,
    project_id: Id,
    url: str,
    name: str,
    kind: PageKind,
    country: str,
) -> DataSource:
    """Register a URL in an already seeded project and rebuild its shared page views."""
    if kind not in ("hospital_list", "sponsor_study_page"):
        raise Invalid("kind must be hospital_list or sponsor_study_page")
    if country not in ("Finland", "Sweden", "Norway", "Denmark"):
        raise Invalid("country must be Finland, Sweden, Norway or Denmark")
    name, url = name.strip(), url.strip()
    if not name:
        raise Invalid("A trial page needs a name")
    if not url.startswith(("https://", "http://")):
        raise Invalid("A trial page needs an http(s) URL")
    sources = await request.get(SourceService)
    registered = await sources.list(project_id)
    by_name = {s.name: s.id for s in registered}
    if any(s.name not in by_name for s in SOURCES):
        raise Invalid("Run ada seed-trials for this project before registering trial pages")
    existing = next(
        (s for s in registered if s.address == url and page_options(s).get("kind") == kind), None
    )
    if existing is None:
        if name in by_name:
            raise Invalid("That source name already belongs to another URL or page kind")
        page = (
            hospital_page(url, name, country)
            if kind == "hospital_list"
            else sponsor_page(url, name)
        )
        existing = await sources.register(project_id, **page.registration())
        by_name[existing.name] = existing.id
    elif kind == "hospital_list" and page_options(existing)["country"] != country:
        raise Invalid("That page is already registered with another country")
    built = await _build(request, project_id, by_name)
    await _publish(request, project_id, by_name, built)
    return await sources.get(existing.id)
