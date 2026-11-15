"""Idempotent registry project and SQL steps, following the waiting-times seed."""

import asyncio
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta

from dishka import AsyncContainer

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id
from ada.core.models.operators import Operator
from ada.core.models.schema import MeasureRole, Roles
from ada.core.models.sources import Provenance
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
    STUDY_PREFIX,
    WEB_REFRESHES_PER_MINUTE,
    hospital_trials_sql,
    study_page,
)
from ada.entrypoints.cli.trials.sources import CTGOV, CTIS, SOURCES

PROJECT = "Nordic cancer trials"
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


async def seed_trials(container: AsyncContainer, refresh: bool = False) -> Id:
    async with container() as request:
        projects = await request.get(ProjectService)
        sources = await request.get(SourceService)
        project = next((p for p in await projects.list() if p.name == PROJECT), None)
        if project is None:
            project = await projects.create(PROJECT)
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
                    await sources.update(saved.id, saved.revision, address=page.address)
        project_id = project.id
    async with container() as request:
        built = await _build(request, project_id, registered)
    study_names = sorted(n for n in registered if n.startswith(STUDY_PREFIX))
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
        web_names = [p.name for p in PAGES] + sorted(study_names)
        for index, name in enumerate(web_names):
            if index:
                await asyncio.sleep(60 / WEB_REFRESHES_PER_MINUTE)
            async with container() as request:
                sources = await request.get(SourceService)
                source = await sources.get(registered[name])
                if name.startswith(STUDY_PREFIX) and source.last_checked_at is not None:
                    if datetime.now(UTC) - source.last_checked_at < timedelta(days=7):
                        continue
                await sources.refresh(source.id, force=True)
        async with container() as request:
            built = await _build(request, project_id, registered)
            for field in fields(built):
                data = await (await request.get(RunService)).query(
                    run.id, getattr(built, field.name).id, "SELECT count(*) AS rows FROM input_0", 1
                )
                print(f"  {field.name}: {data.rows[0][0]} rows")
    async with container() as request:
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
    print(
        f"  pages: {len(PAGES)} hospital, {len(study_names)} study; "
        f"full web refresh estimate: {len(PAGES) + 5 * len(study_names)} credits "
        "(1/scrape, about 5/extract; fresh snapshots are reused)"
    )
    print(f"Project {PROJECT!r}: {project_id}")
    for dashboard in dashboards:
        print(f"  dashboard {dashboard.id}  {dashboard.name}")
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
    pages = [await pipelines.add_source(project_id, sources[p.name], SEED) for p in PAGES]
    hospital_trials = await transform(hospital_trials_sql(), pages)
    gaps = await transform(HOSPITAL_TRIAL_GAPS, [hospital_trials, trials, sites])
    sponsor_inputs = [
        await pipelines.add_source(project_id, sources[name], SEED)
        for name in sorted(sources)
        if name.startswith(STUDY_PREFIX)
    ]
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
    )
