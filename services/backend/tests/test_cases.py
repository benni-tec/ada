"""Case types, cases and the models on them: the field rules, saving under a key, the
automatic and the requested results, no backfill, and the open-case order."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid7

import pytest
from fastapi.testclient import TestClient

from ada.adapters.memory.repositories import (
    MemoryCaseRepository,
    MemoryDataSourceRepository,
    MemoryProjectRepository,
    MemoryStatisticalModelRepository,
    MemoryStore,
)
from ada.adapters.memory.tasks import RecordingTaskDispatcher
from ada.adapters.transactions import PendingWork
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.cases import Field, FieldType, ResultTrigger
from ada.core.models.errors import Invalid
from ada.core.models.projects import Project
from ada.core.services.cases.fields import (
    check_key,
    check_values,
    compatible,
    coverage,
)
from ada.core.services.cases.service import Cases
from ada.core.services.statistical_models.pathway import pathway_spec
from ada.core.services.statistical_models.service import PATHWAY_CASE_TYPE, StatisticalModels
from api_support import Overrides, new_project, send, serve
from fakes import FixedClock

pytestmark = pytest.mark.anyio

ACTOR = Actor(kind=ActorKind.USER, name="test")
SITE = Field(name="site", type=FieldType.ENUM, levels=("lung", "colorectal"), required=True)

# Demo profile 1: lung, the X-ray on day 27, treatment start overdue by 3 days on day 74.
OVERDUE: dict[str, Any] = {
    "site": "lung",
    "sex": "female",
    "age_band": "60-69",
    "education": "basic",
    "route": "public_health_centre",
    "intent": "curative",
    "modality": "surgery",
    "presentation": ["lung_symptoms_smoker", "lung_imaging"],
    "days": {
        "symptoms_to_contact": 51,
        "contact_to_physician": 14,
        "physician_to_imaging": 13,
        "imaging_to_referral": 1,
        "referral_to_specialist": 8,
        "specialist_to_workup": 26,
        "workup_to_treatment": 12,
    },
    "county": "Pirkanmaa",
}
# The same pathway, early: just referred, nothing overdue yet.
EARLY: dict[str, Any] = {
    **OVERDUE,
    "days": {
        "symptoms_to_contact": 10,
        "contact_to_physician": 3,
        "physician_to_imaging": 4,
        "imaging_to_referral": 1,
        "referral_to_specialist": 2,
    },
    "county": "Lappi",
}


# The field rules.


def test_values_are_checked_against_their_fields() -> None:
    fields = (
        SITE,
        Field(name="days", type=FieldType.DAY_MAP, levels=("a", "b")),
        Field(name="seen", type=FieldType.DATE),
    )
    checked = check_values(fields, {"site": "lung", "days": {"b": 2, "a": 1}, "seen": "2026-11-15"})
    assert checked["days"] == {"a": 1, "b": 2}
    with pytest.raises(Invalid, match="site is required"):
        check_values(fields, {})
    with pytest.raises(Invalid, match="Unknown fields: x"):
        check_values(fields, {"site": "lung", "x": 1})
    with pytest.raises(Invalid, match="one of"):
        check_values(fields, {"site": "liver"})
    with pytest.raises(Invalid, match="0 or more"):
        check_values(fields, {"site": "lung", "days": {"a": -1}})
    with pytest.raises(Invalid, match="date"):
        check_values(fields, {"site": "lung", "seen": "15.11.2026"})


def test_coverage_names_what_a_model_lacks() -> None:
    needs = (SITE, Field(name="sex", type=FieldType.ENUM, levels=("female", "male")))
    assert coverage((SITE, needs[1], Field(name="county", type=FieldType.TEXT)), needs) == []
    gaps = {
        g.field: g.problem for g in coverage((SITE.model_copy(update={"required": False}),), needs)
    }
    assert gaps == {"site": "must be required", "sex": "missing (enum)"}
    wider = SITE.model_copy(update={"levels": ("lung", "colorectal", "liver")})
    assert "liver" in coverage((wider, needs[1]), needs)[0].problem
    text_sex = Field(name="sex", type=FieldType.TEXT)
    assert coverage((SITE, text_sex), needs)[0].problem == "is text, needs enum"


def test_a_schema_with_cases_can_only_grow() -> None:
    old = (SITE, Field(name="note", type=FieldType.TEXT))
    grown = (
        SITE.model_copy(update={"levels": ("lung", "colorectal", "pancreas")}),
        Field(name="note", type=FieldType.TEXT),
        Field(name="county", type=FieldType.TEXT),
    )
    assert compatible(old, grown) == []
    assert compatible(old, (SITE,)) == ["note is removed"]
    narrowed = SITE.model_copy(update={"levels": ("lung",)})
    assert compatible(old, (narrowed, old[1])) == ["site loses levels colorectal"]
    required = Field(name="county", type=FieldType.TEXT, required=True)
    assert compatible(old, (*old, required)) == ["county is new and required"]


def test_a_key_is_ours_and_never_a_person() -> None:
    check_key("SYN-0042")
    check_key("apotti:1234.56")
    for code in ("131052-308T", "010101A123N", "id 131052-308T"):
        with pytest.raises(Invalid, match="personal identity code"):
            check_key(code)
    with pytest.raises(Invalid, match="1 to 128"):
        check_key("has space")


# The services on the memory repositories.


class World:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.project = Project(id=uuid7(), name="Nordic cancer care", created_at=FixedClock().now())
        self.store.projects[self.project.id] = self.project
        repo = MemoryCaseRepository(self.store)
        models = MemoryStatisticalModelRepository(self.store)
        self.models = StatisticalModels(
            models,
            MemoryProjectRepository(self.store),
            repo,
            None,
            FixedClock(),  # type: ignore[arg-type]
        )
        self.dispatcher = RecordingTaskDispatcher()
        self.after_commit = PendingWork()
        self.cases = Cases(
            repo,
            models,
            FixedClock(),
            MemoryDataSourceRepository(self.store),
            self.dispatcher,
            self.after_commit,
        )

    async def pathway(self) -> tuple[Any, Any]:
        version = await self.models.create_pathway_model(self.project.id, ACTOR)
        model = await self.models.get(version.model_id)
        assert model.case_type_id is not None
        return model, await self.cases.get_type(model.case_type_id)

    async def second_model(self, case_type_id: Any, auto_run: bool) -> Any:
        version = await self.models.create(
            self.project.id,
            "Second opinion",
            "",
            pathway_spec(),
            ACTOR,
            case_type_id=case_type_id,
            auto_run=auto_run,
        )
        return await self.models.get(version.model_id)


async def test_the_pathway_model_comes_with_its_case_type() -> None:
    world = World()
    model, case_type = await world.pathway()
    assert model.auto_run and case_type.name == PATHWAY_CASE_TYPE
    assert {"site", "sex", "days", "presentation", "county", "referred_by"} <= {
        f.name for f in case_type.fields
    }
    # A second pathway model reuses the case type.
    again = await world.models.create_pathway_model(world.project.id, ACTOR)
    assert (await world.models.get(again.model_id)).case_type_id == case_type.id
    assert len(await world.cases.list_types(world.project.id)) == 1


async def test_saving_a_case_runs_the_automatic_models_and_keeps_history() -> None:
    world = World()
    model, case_type = await world.pathway()
    saved = await world.cases.put_case(case_type.id, "SYN-0042", EARLY, ACTOR)
    assert saved.ran == (model.id,)
    assert [r.trigger for r in saved.results] == [ResultTrigger.AUTO]
    assert saved.results[0].section.summary == "First specialist visit due in 7 days"
    assert {e.step for e in saved.events} == set(EARLY["days"])
    # The county is the case type's own field: saved, not passed to the model.
    assert saved.case.values["county"] == "Lappi"

    later = await world.cases.put_case(case_type.id, "SYN-0042", OVERDUE, ACTOR)
    assert later.case.revision == 2 and later.case.id == saved.case.id
    assert len(later.results) == 2 and later.results[0].case_revision == 2
    assert later.results[0].section.summary == "Treatment start overdue by 3 days"
    assert later.results[0].section.status == "urgent"
    # Only the steps whose days changed or started were recorded again: imaging to referral
    # stayed at 1 day.
    again = [e.step for e in later.events[len(saved.events) :]]
    assert "imaging_to_referral" not in again and "workup_to_treatment" in again


async def test_a_model_on_request_runs_only_when_asked_and_is_never_backfilled() -> None:
    world = World()
    _, case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    manual = await world.second_model(case_type.id, auto_run=False)
    on_case = {m.model_id: m for m in await world.cases.models(case_type.id, "SYN-0001")}
    assert on_case[manual.id].latest is None and on_case[manual.id].results == 0
    # Saving again does not run it either.
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    assert (await world.cases.models(case_type.id, "SYN-0001"))[1].latest is None
    result = await world.cases.evaluate(case_type.id, "SYN-0001", manual.id, ACTOR)
    assert result.trigger is ResultTrigger.REQUEST
    on_case = {m.model_id: m for m in await world.cases.models(case_type.id, "SYN-0001")}
    assert on_case[manual.id].latest == result
    # A new automatic model has no result for old cases until they are saved again.
    late = await world.second_model(case_type.id, auto_run=True)
    assert [c.latest for c in await world.cases.model_cases(late.id)] == [None]


async def test_a_model_needs_a_case_type_that_covers_it() -> None:
    world = World()
    thin = await world.cases.create_type(world.project.id, "Thin", "", (SITE,), ACTOR)
    with pytest.raises(Invalid, match="does not cover"):
        await world.second_model(thin.id, auto_run=True)


async def test_a_case_type_change_must_keep_its_cases_and_models() -> None:
    world = World()
    _, case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-0001", OVERDUE, ACTOR)
    grown = (*case_type.fields, Field(name="clinic", type=FieldType.TEXT))
    changed = await world.cases.update_type(case_type.id, fields=grown)
    assert changed.revision == case_type.revision + 1
    with pytest.raises(Invalid, match="can only grow"):
        await world.cases.update_type(case_type.id, fields=case_type.fields[:-1])
    empty = await world.cases.create_type(world.project.id, "Empty", "", (SITE,), ACTOR)
    with pytest.raises(Invalid, match="identity code"):
        await world.cases.put_case(empty.id, "131052-308T", {"site": "lung"}, ACTOR)


async def test_open_cases_put_the_overdue_first_and_never_rank_by_survival() -> None:
    world = World()
    _, case_type = await world.pathway()
    await world.cases.put_case(case_type.id, "SYN-EARLY", EARLY, ACTOR)
    await world.cases.put_case(case_type.id, "SYN-LATE", OVERDUE, ACTOR)
    done = {
        **OVERDUE,
        "days": {**OVERDUE["days"], "workup_to_treatment": 5},
        "treatment_started": True,
    }
    await world.cases.put_case(case_type.id, "SYN-DONE", done, ACTOR)
    open_ = await world.cases.open_cases(case_type.id)
    assert [c.case.key for c in open_] == ["SYN-LATE", "SYN-EARLY"]


# The REST surface.


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


def test_rest_saves_a_case_and_evaluates_on_request(client: TestClient) -> None:
    project = new_project(client, "Nordic cancer care")
    version = send(client, "POST", f"/projects/{project['id']}/models/pathway", None, 201)
    [case_type] = send(client, "GET", f"/projects/{project['id']}/case-types")
    base = f"/case-types/{case_type['id']}"
    saved = send(client, "PUT", f"{base}/cases/SYN-0042", {"values": OVERDUE})
    assert saved["ran"] == [version["model_id"]]
    assert saved["results"][0]["section"]["summary"] == "Treatment start overdue by 3 days"
    [on_case] = send(client, "GET", f"{base}/cases/SYN-0042/models")
    assert on_case["auto_run"] and on_case["results"] == 1
    result = send(
        client,
        "POST",
        f"{base}/cases/SYN-0042/evaluate",
        {"model_id": version["model_id"]},
        201,
    )
    assert result["trigger"] == "request"
    [row] = send(client, "GET", f"/models/{version['model_id']}/cases")
    assert row["latest"]["id"] == result["id"]
    assert [c["case"]["key"] for c in send(client, "GET", f"{base}/open-cases")] == ["SYN-0042"]
    refused = client.put(f"/api{base}/cases/131052-308T", json={"values": OVERDUE})
    assert refused.status_code == 422
