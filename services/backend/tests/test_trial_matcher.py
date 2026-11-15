"""The trial matcher as a model on the cancer case type: it reads Felix's case_trials and
county_cities steps whenever it runs, keeps the trials of the case's cancer group only, shows
sex and age limits without applying them, sorts by distance from the county's city, and never
asks for attention."""

import re
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
from ada.core.models.statistical_models import TrialMatcherSpec
from ada.core.services.cases.service import Cases
from ada.core.services.ports.exploration import Clauses, Explored
from ada.core.services.statistical_models.service import StatisticalModels
from fakes import FixedClock
from test_cases import OVERDUE

pytestmark = pytest.mark.anyio

ACTOR = Actor(kind=ActorKind.USER, name="test")
TRIALS, COUNTIES = "op_case_trials", "op_county_cities"
COLUMNS = (
    "nct_id title phase sex min_age_years max_age_years eligibility recruiting_countries "
    "finnish_site helsinki_facility helsinki_city helsinki_country helsinki_km "
    "kuopio_facility kuopio_city kuopio_country kuopio_km "
    "oulu_facility oulu_city oulu_country oulu_km url"
).split()


def trial(nct: str, group: str, sex: str, ages: tuple[Any, Any], finnish: bool, km: float):
    site = ("HUS", "Helsinki", "Finland") if finnish else ("Karolinska", "Stockholm", "Sweden")
    return {
        "group": group,
        "row": (
            nct,
            f"Trial {nct}",
            "PHASE2",
            sex,
            *ages,
            "Inclusion: adults.",
            site[2],
            finnish,
            *site,
            km,
            *site,
            km + 300,
            *site,
            km + 500,
            f"https://clinicaltrials.gov/study/{nct}",
        ),
    }


DATA = [
    trial("NCT1", "lung", "ALL", (18, 75), True, 5),
    trial("NCT2", "lung", "FEMALE", (50, None), False, 400),
    trial("NCT3", "lung", "MALE", (18, 40), False, 200),
    trial("NCT4", "pancreas", "ALL", (18, 65), False, 900),
]


class TrialsData:
    """The two data steps: the trials of the group named in the query's where clause, and
    the city of the county named in it. Each query is a run of its own."""

    def __init__(self) -> None:
        self.trials = list(DATA)
        self.asked: list[tuple[str, Clauses]] = []

    async def query(self, operator_id: str, clauses: Clauses, actor: Actor, **_: Any) -> Explored:
        self.asked.append((operator_id, clauses))
        if operator_id == TRIALS:
            group = re.search(r"'([^']*)'\)$", clauses.where or "").group(1)  # type: ignore[union-attr]
            rows = tuple(t["row"] for t in self.trials if t["group"] == group)
            columns = COLUMNS
        else:
            county = re.search(r"'(.*)'$", clauses.where or "").group(1)  # type: ignore[union-attr]
            known = {"Lappi": "oulu", "Pohjois-Savo": "kuopio"}
            rows = ((known[county],),) if county in known else ()
            columns = ["city"]
        return Explored(
            rows=Rows(columns=tuple(Column(name=c, type="text") for c in columns), rows=rows),
            run_id=uuid7(),
        )


class World:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.project = Project(id=uuid7(), name="Nordic cancer care", created_at=FixedClock().now())
        self.store.projects[self.project.id] = self.project
        repo = MemoryCaseRepository(self.store)
        models = MemoryStatisticalModelRepository(self.store)
        self.data = TrialsData()
        self.models = StatisticalModels(
            models, MemoryProjectRepository(self.store), repo, self.data, FixedClock()
        )
        self.cases = Cases(
            repo,
            models,
            FixedClock(),
            MemoryDataSourceRepository(self.store),
            RecordingTaskDispatcher(),
            PendingWork(),
            self.data,
        )

    async def matcher(self, county_step: bool = True, auto_run: bool = False) -> tuple[Any, Any]:
        pathway = await self.models.create_pathway_model(self.project.id, ACTOR)
        version = await self.models.create_trial_matcher(
            self.project.id,
            TRIALS,
            ACTOR,
            COUNTIES if county_step else None,
            auto_run=auto_run,
        )
        return pathway, await self.models.get(version.model_id)


async def test_the_matcher_lands_on_the_cancer_case_type_and_reads_nothing_until_it_runs() -> None:
    world = World()
    pathway, model = await world.matcher()
    assert model.case_type_id == (await world.models.get(pathway.model_id)).case_type_id
    assert not model.auto_run
    assert world.data.asked == []


async def test_a_case_gets_its_cancer_groups_trials_nearest_first_whatever_its_sex_and_age() -> (
    None
):
    world = World()
    _, model = await world.matcher()
    type_id = model.case_type_id
    woman_70s = {**OVERDUE, "age_band": "70-79", "county": "Pirkanmaa"}
    await world.cases.put_case(type_id, "SYN-1", woman_70s, ACTOR)
    result = await world.cases.evaluate(type_id, "SYN-1", model.id, ACTOR)
    section = result.section
    # Lung trials only, the men-only and the 18-40 one included: sex and age are shown.
    matches = section.body["matches"]
    assert [m["nct_id"] for m in matches] == ["NCT1", "NCT3", "NCT2"]
    assert [(m["sex"], m["age"]) for m in matches] == [
        ("ALL", "partly"),
        ("MALE", "outside"),
        ("FEMALE", "inside"),
    ]
    assert section.summary == "3 recruiting trials, nearest 5 km from Helsinki"
    assert section.attention.open is False
    # The result says which runs it read.
    assert set(section.reads) == {"trials", "county"}


async def test_distances_are_from_the_city_the_county_step_names() -> None:
    world = World()
    _, model = await world.matcher()
    await world.cases.put_case(model.case_type_id, "SYN-N", {**OVERDUE, "county": "Lappi"}, ACTOR)
    section = (await world.cases.evaluate(model.case_type_id, "SYN-N", model.id, ACTOR)).section
    assert section.body["city"] == "oulu"
    assert section.body["matches"][0]["nearest"]["km"] == 505
    # Without the county step, or for a county it does not list, from Helsinki.
    plain = World()
    _, other = await plain.matcher(county_step=False)
    await plain.cases.put_case(other.case_type_id, "SYN-N", {**OVERDUE, "county": "Lappi"}, ACTOR)
    section = (await plain.cases.evaluate(other.case_type_id, "SYN-N", other.id, ACTOR)).section
    assert section.body["city"] == "helsinki" and "county" not in section.reads


async def test_the_matcher_is_as_current_as_its_data_step() -> None:
    world = World()
    _, model = await world.matcher(auto_run=True)
    first = await world.cases.put_case(model.case_type_id, "SYN-1", OVERDUE, ACTOR)
    world.data.trials = [t for t in world.data.trials if t["row"][0] != "NCT1"]
    second = await world.cases.put_case(model.case_type_id, "SYN-1", OVERDUE, ACTOR)
    counts = [
        next(r for r in saved.results if r.model_id == model.id).section.columns["trials"]
        for saved in (first, second)
    ]
    assert counts == [3, 2]


async def test_a_new_version_takes_a_spec_of_the_models_own_kind() -> None:
    world = World()
    pathway, model = await world.matcher()
    moved = TrialMatcherSpec(operator_id="op_case_trials_2", county_operator_id=COUNTIES)
    version = await world.models.add_version(model.id, moved, ACTOR)
    assert version.version == 2 and version.spec == moved
    with pytest.raises(Invalid, match="is a patient_pathway model"):
        await world.models.add_version(pathway.model_id, moved, ACTOR)
    # The survival model's operations refuse a matcher.
    with pytest.raises(Invalid, match="no profile evaluation"):
        await world.models.population(model.id)
