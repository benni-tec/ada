"""Idempotent registry project and SQL steps, following the waiting-times seed."""

import asyncio
from dataclasses import dataclass, fields

from dishka import AsyncContainer

from ada.core.models.actors import Actor, ActorKind
from ada.core.models.base import Id
from ada.core.models.operators import Operator
from ada.core.models.schema import MeasureRole, Roles
from ada.core.models.sources import Provenance
from ada.core.models.statistical_models import TrialMatcherSpec
from ada.core.services.ports.cases import CaseService
from ada.core.services.ports.pipelines import PipelineService
from ada.core.services.ports.projects import ProjectService
from ada.core.services.ports.runs import RunService
from ada.core.services.ports.sessions import SessionService
from ada.core.services.ports.sources import SourceService
from ada.core.services.ports.statistical_models import StatisticalModelService
from ada.entrypoints.cli.trials import steps
from ada.entrypoints.cli.trials.dashboards import create_dashboards
from ada.entrypoints.cli.trials.monitoring import create_monitoring
from ada.entrypoints.cli.trials.sources import CTGOV, CTIS, SOURCES

PROJECT = "Nordic cancer trials"
# The case type the matcher makes for itself when the project has none that covers it.
CASE_TYPE = "Cancer trial candidate"


def agent_instructions(case_type: str = CASE_TYPE) -> str:
    """What the project's agent is told, naming the case type the matcher runs on."""
    return (
        f'For a patient, save a case on the "{case_type}" case type with set_case: '
        "a new key such as PATIENT-1, never a name or identity code, and the site, sex, age group "
        "and wellbeing services county as told. The trial matcher runs on save: answer from its "
        "result, in its order, nearest first, with each nearest site's city and km and the city "
        "the distances are from. Quote each eligibility text as written, never as a verdict. Sex "
        "and age limits are information only: never filter or judge by them or any other "
        "criterion, never say a patient qualifies, rank by efficacy or promise anything. End by "
        "saying to take the list to their oncologist, who decides eligibility. For trials in "
        "general, use the dashboards and data steps."
    )


AGENT_INSTRUCTIONS = agent_instructions()
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
    county_cities: Operator


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
        sessions = await request.get(SessionService)
        session = next((s for s in await sessions.list(project_id) if s.title == SESSION), None)
        if session is None:
            session = await sessions.create(project_id, SESSION)
        # A reseed after the SQL changed builds new operators; record those too, so the
        # session points the agent at the current steps.
        recorded = {e.ref for e in await sessions.entries(session.id)}
        for field in fields(built):
            operator_id = getattr(built, field.name).id
            if str(operator_id) not in recorded:
                await sessions.record_operator(
                    session.id,
                    operator_id,
                    f"{field.name}: registry data transformed with SQL",
                    SEED,
                )
        dashboards = await create_dashboards(request, project_id, session.id, built, SEED)
        await create_monitoring(request, project_id, session.id, registered, built, SEED)
        case_type = await create_matcher(request, project_id, built)
        # The instructions name the case type the matcher landed on, which is an existing
        # one when the project already had a type that covers it.
        projects = await request.get(ProjectService)
        current = await projects.get(project_id)
        await projects.update(
            project_id, current.revision, agent_instructions=agent_instructions(case_type)
        )
    if refresh:
        for index, source in enumerate(SOURCES):
            if index:
                await asyncio.sleep(REFRESH_DELAY_SECONDS)
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
    for dashboard in dashboards:
        print(f"  dashboard {dashboard.id}  {dashboard.name}")
    return project_id


async def create_matcher(request: AsyncContainer, project_id: Id, steps: TrialSteps) -> str:
    """The project's trial matcher, running on every save of a case of its case type and
    reading case_trials and county_cities when it runs; the case type's name. A reseed that
    rebuilt those steps gives the matcher a new version reading the new ones, and puts it
    back on a case type and its runs on save back on."""
    models = await request.get(StatisticalModelService)
    cases = await request.get(CaseService)
    spec = TrialMatcherSpec(
        operator_id=steps.case_trials.id, county_operator_id=steps.county_cities.id
    )
    matcher = next((m for m in await models.list(project_id) if m.kind == spec.kind), None)
    if matcher is None:
        version = await models.create_trial_matcher(
            project_id, spec.operator_id, SEED, spec.county_operator_id, auto_run=True
        )
        matcher = await models.get(version.model_id)
    else:
        current = (await models.version(matcher.id)).spec
        if not isinstance(current, TrialMatcherSpec) or (
            current.operator_id,
            current.county_operator_id,
        ) != (spec.operator_id, spec.county_operator_id):
            await models.add_version(matcher.id, spec, SEED)
        # The instructions promise a result on every save: a matcher taken off its case
        # type goes back on one, and one that stopped running on save runs again.
        if matcher.case_type_id is None:
            matcher = await models.attach_default_case_type(matcher.id, SEED)
        elif not matcher.auto_run:
            matcher = await models.set_case_type(matcher.id, matcher.case_type_id, True)
    assert matcher.case_type_id is not None
    return (await cases.get_type(matcher.case_type_id)).name


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
    counties = await transform(steps.COUNTY_CITIES, [])
    return TrialSteps(trials, sites, doors, ctis_trials, pending, rates, cases, counties)
