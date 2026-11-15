"""The trial matcher as a model on the cancer case type: it pins the trials of its cancer
groups from a trials data step, matches a case on site, sex and age group only, puts trials
with a Finnish site first, then the nearest, and never asks for attention."""

from typing import Any
from uuid import uuid7

import pytest

from ada.adapters.memory.repositories import (
    MemoryCaseRepository,
    MemoryDataSourceRepository,
    MemoryProjectRepository,
    MemoryStatisticalModelRepository,
    MemoryStore,
)
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.transactions import PendingWork
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.analysis import Column, Rows
from ada.core.models.errors import Invalid
from ada.core.models.projects import Project
from ada.core.models.statistical_models import TrialCompiled
from ada.core.services.cases.service import Cases
from ada.core.services.statistical_models.service import StatisticalModels
from fakes import FixedClock
from test_cases import OVERDUE
from test_statistical_models import RowsExploration

pytestmark = pytest.mark.anyio

ACTOR = Actor(kind=ActorKind.USER, name="test")
COLUMNS = (
    "nct_id title phase conditions cancer_groups sex min_age_years max_age_years eligibility "
    "recruiting_countries finnish_site "
    "helsinki_facility helsinki_city helsinki_country helsinki_km "
    "kuopio_facility kuopio_city kuopio_country kuopio_km "
    "oulu_facility oulu_city oulu_country oulu_km url"
).split()


def trial(nct: str, groups: str, sex: str, ages: tuple[Any, Any], finnish: bool, km: float):
    site = ("HUS" if finnish else "Karolinska", "Helsinki" if finnish else "Stockholm")
    country = "Finland" if finnish else "Sweden"
    near = [(*site, country, km), (*site, country, km + 300), (*site, country, km + 500)]
    return (
        nct,
        f"Trial {nct}",
        "PHASE2",
        groups,
        groups,
        sex,
        *ages,
        "Inclusion: adults.",
        country,
        finnish,
        *[v for city in near for v in city],
        f"https://clinicaltrials.gov/study/{nct}",
    )


ROWS = Rows(
    columns=tuple(Column(name=c, type="text") for c in COLUMNS),
    rows=(
        trial("NCT1", "lung", "ALL", (18, 75), True, 5),
        trial("NCT2", "lung, colorectal", "FEMALE", (50, None), False, 400),
        trial("NCT3", "pancreas", "ALL", (18, 65), False, 900),
    ),
)


class World:
    def __init__(self, rows: Rows = ROWS) -> None:
        self.store = MemoryStore()
        self.project = Project(id=uuid7(), name="Nordic cancer care", created_at=FixedClock().now())
        self.store.projects[self.project.id] = self.project
        repo = MemoryCaseRepository(self.store)
        models = MemoryStatisticalModelRepository(self.store)
        self.exploration = RowsExploration(rows)
        self.models = StatisticalModels(
            models, MemoryProjectRepository(self.store), repo, self.exploration, FixedClock()
        )
        self.cases = Cases(
            repo,
            models,
            FixedClock(),
            MemoryDataSourceRepository(self.store),
            RecordingTaskDispatcher(),
            PendingWork(),
        )


async def matcher_on_pathway(world: World) -> tuple[Any, Any, Any]:
    pathway = await world.models.create_pathway_model(world.project.id, ACTOR)
    version = await world.models.create_trial_matcher(world.project.id, "op_case_trials", ACTOR)
    model = await world.models.get(version.model_id)
    return pathway, model, version


async def test_the_matcher_lands_on_the_cancer_case_type_and_pins_its_trials() -> None:
    world = World()
    pathway, model, version = await matcher_on_pathway(world)
    assert model.case_type_id == (await world.models.get(pathway.model_id)).case_type_id
    assert not model.auto_run
    assert isinstance(version.compiled, TrialCompiled)
    assert [t.nct_id for t in version.compiled.trials] == ["NCT1", "NCT2", "NCT3"]
    assert version.compiled.trials[1].cancer_groups == ("lung", "colorectal")
    [(operator, clauses)] = world.exploration.asked
    assert operator == "op_case_trials" and clauses.group_by == "nct_id"
    assert "colorectal|lung|pancreas" in (clauses.where or "")


async def test_a_case_is_matched_on_site_sex_and_age_only() -> None:
    world = World()
    _, model, _ = await matcher_on_pathway(world)
    type_id = model.case_type_id
    saved = await world.cases.put_case(type_id, "SYN-1", OVERDUE, ACTOR)
    # The matcher runs on request only: saving ran the pathway model alone.
    assert model.id not in saved.ran
    result = await world.cases.evaluate(type_id, "SYN-1", model.id, ACTOR)
    section = result.section
    assert section.summary == "2 recruiting trials, 1 with a Finnish site"
    assert [m["nct_id"] for m in section.body["matches"]] == ["NCT1", "NCT2"]
    assert [m["age"] for m in section.body["matches"]] == ["fits", "fits"]
    assert section.attention.open is False and section.columns["nearest_km"] == 5
    # A man is not offered the women's trial; 70-79 is only partly inside 18-75.
    man = {**OVERDUE, "sex": "male", "age_band": "70-79"}
    await world.cases.put_case(type_id, "SYN-2", man, ACTOR)
    other = (await world.cases.evaluate(type_id, "SYN-2", model.id, ACTOR)).section
    assert [(m["nct_id"], m["age"]) for m in other.body["matches"]] == [("NCT1", "partly")]
    assert other.columns["age_uncertain"] == 1


async def test_distance_is_measured_from_the_case_county_city() -> None:
    world = World()
    _, model, _ = await matcher_on_pathway(world)
    north = {**OVERDUE, "county": "Lappi"}
    await world.cases.put_case(model.case_type_id, "SYN-N", north, ACTOR)
    section = (await world.cases.evaluate(model.case_type_id, "SYN-N", model.id, ACTOR)).section
    assert section.body["city"] == "oulu"
    assert section.body["matches"][0]["nearest"]["km"] == 505


async def test_refreshing_makes_a_new_version_and_keeps_old_results() -> None:
    world = World()
    _, model, _ = await matcher_on_pathway(world)
    await world.cases.put_case(model.case_type_id, "SYN-1", OVERDUE, ACTOR)
    first = await world.cases.evaluate(model.case_type_id, "SYN-1", model.id, ACTOR)
    world.exploration.rows = Rows(columns=ROWS.columns, rows=ROWS.rows[2:])
    second = await world.models.refresh_trial_matcher(model.id, ACTOR)
    assert second.version == 2
    again = await world.cases.evaluate(model.case_type_id, "SYN-1", model.id, ACTOR)
    assert (first.version, first.section.columns["trials"]) == (1, 2)
    assert (again.version, again.section.summary) == (2, "No recruiting trial matches")
    # The survival model's operations refuse a matcher.
    with pytest.raises(Invalid, match="no profile evaluation"):
        await world.models.population(model.id)
    with pytest.raises(Invalid, match="not a trial matcher"):
        await world.models.refresh_trial_matcher(
            (await world.models.list(world.project.id))[0].id, ACTOR
        )


async def test_too_many_trials_are_refused_rather_than_cut() -> None:
    world = World(ROWS.model_copy(update={"truncated": True}))
    with pytest.raises(Invalid, match="narrow the groups"):
        await world.models.create_trial_matcher(world.project.id, "op_case_trials", ACTOR)
