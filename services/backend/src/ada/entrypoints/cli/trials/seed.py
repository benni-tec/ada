"""Idempotent registry project and SQL steps, following the waiting-times seed."""

from dataclasses import dataclass, fields

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
from ada.entrypoints.cli.trials.monitoring import create_monitoring
from ada.entrypoints.cli.trials.sources import CTGOV, CTIS, SOURCES

PROJECT = "Nordic cancer trials"
SESSION = "Nordic cancer trials"
SEED = Actor(kind=ActorKind.SYSTEM, name="ada seed-trials")


@dataclass
class TrialSteps:
    trials: Operator
    trial_sites: Operator
    trial_doors: Operator
    ctis_trials: Operator
    ctis_finland_pending: Operator
    trial_rates: Operator
    case_trials: Operator


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
        project_id = project.id
    async with container() as request:
        built = await _build(request, project_id, registered)
        session = next(
            s
            for s in await (await request.get(SessionService)).list(project_id)
            if s.title == SESSION
        )
        await create_monitoring(request, project_id, session.id, registered, built, SEED)
    if refresh:
        for source in SOURCES:
            async with container() as request:
                await (await request.get(SourceService)).refresh(
                    registered[source.name], force=True
                )
        async with container() as request:
            run = await (await request.get(RunService)).start(project_id, SEED)
        for field in fields(built):
            async with container() as request:
                data = await (await request.get(RunService)).query(
                    run.id, getattr(built, field.name).id, "SELECT count(*) AS rows FROM input_0", 1
                )
            print(f"  {field.name}: {data.rows[0][0]} rows")
    print(f"Project {PROJECT!r}: {project_id}")
    return project_id


async def _build(request: AsyncContainer, project_id: Id, sources: dict[str, Id]) -> TrialSteps:
    pipelines = await request.get(PipelineService)
    sessions = await request.get(SessionService)
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
    built = TrialSteps(trials, sites, doors, ctis_trials, pending, rates, cases)
    session = next((s for s in await sessions.list(project_id) if s.title == SESSION), None)
    if session is None:
        session = await sessions.create(project_id, SESSION)
        for field in fields(built):
            await sessions.record_operator(
                session.id,
                getattr(built, field.name).id,
                f"{field.name}: registry data transformed with SQL",
                SEED,
            )
    return built
