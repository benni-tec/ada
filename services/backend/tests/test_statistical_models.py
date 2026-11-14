"""The patient pathway model: the evaluator on the shipped spec (trigger, deadlines, days
behind, survival per setting, levers, flags), the build (targets, residual), the service on
the memory repositories, and the REST and MCP surfaces, which create no runs."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ada.adapters.memory.repositories import MemoryStore
from ada.config import Settings
from ada.core.models.actors import Actor, ActorKind
from ada.core.models.errors import Invalid
from ada.core.models.statistical_models import (
    DeadlineStatus,
    EvaluationInputs,
    EvidenceGrade,
    Intent,
    ModelVersion,
    PathwayStep,
)
from ada.core.services.statistical_models.build import compile_spec
from ada.core.services.statistical_models.evaluate import evaluate
from ada.core.services.statistical_models.pathway import pathway_spec
from api_support import Overrides, call, mcp_client, new_project, resolve, send, serve
from fakes import FixedClock

pytestmark = pytest.mark.anyio

S = PathwayStep
ACTOR = Actor(kind=ActorKind.USER, name="test")

# The mockup's example: a woman of 64 with lung cancer, first contact at a health centre,
# a 14-day wait for a physician, an X-ray on day 27 that fires the trigger, and nine days
# into the step from the completed work-up to the treatment plan.
EXAMPLE = EvaluationInputs(
    site="lung",
    sex="female",
    age_band="60-69",
    education="basic",
    route="public_health_centre",
    presentation=("lung_symptoms_smoker", "lung_imaging"),
    days={
        S.SYMPTOMS_TO_CONTACT: 51,
        S.CONTACT_TO_PHYSICIAN: 14,
        S.PHYSICIAN_TO_IMAGING: 13,
        S.IMAGING_TO_REFERRAL: 1,
        S.REFERRAL_TO_SPECIALIST: 8,
        S.SPECIALIST_TO_WORKUP: 26,
        S.WORKUP_TO_TREATMENT: 12,
    },
)


@pytest.fixture(scope="module")
def version() -> ModelVersion:
    from uuid import uuid7

    spec = pathway_spec()
    return ModelVersion(
        id=uuid7(),
        model_id=uuid7(),
        version=1,
        spec=spec,
        compiled=compile_spec(spec),
        created_by=ACTOR,
        created_at=FixedClock().now(),
    )


def test_build_takes_the_median_target_and_computes_the_residual(version: ModelVersion) -> None:
    targets = version.compiled.targets["lung"]
    # Norway 42, Sweden 44 and Denmark 44 for surgery; 35, 40 and 41 for drugs.
    assert targets["pathway"]["surgery"] == 44
    assert targets["pathway"]["drugs"] == 40
    # Norway 7 and Denmark 6: the median 6.5 rounds to even.
    assert targets[S.REFERRAL_TO_SPECIALIST.value]["any"] == 6
    figures = {(p.site, p.sex): p for p in version.compiled.population}
    men = figures[("lung", "male")]
    # The Nordic level, lowered by Finland's extra days, then what is left to the observed figure.
    assert men.baseline == 31
    assert men.baseline > men.timing_adjusted > men.observed == 18
    assert men.residual > 1
    assert "upper bound" in men.note
    # The overall-mortality HRs are used unconverted until an excess share is loaded.
    assert any("unconverted" in w for w in version.compiled.warnings)


def test_the_build_checks_itself_against_figures_it_was_not_built_from(
    version: ModelVersion,
) -> None:
    checks = {c.name: c for c in version.compiled.validation}
    # Hanna's own examples: an 8-week delay compounds the per-4-weeks HR twice.
    hanna = checks["delay_post:lung: 8 weeks of delay"]
    assert hanna.expected == hanna.predicted == round(1.06**2, 4)
    # Pokhrel's gap, basic vs high education, against Zai's direct HR, which the model
    # carries: 1.25 observed in 1996-2005 against 1.22 estimated for 2000-2019.
    women = checks["education gap, lung, female"]
    assert women.predicted == 1.22
    assert 1.2 < women.expected < 1.3
    assert "Pokhrel" in women.note


def test_colorectal_and_pancreas_have_their_own_triggers_and_targets(version: ModelVersion) -> None:
    targets = version.compiled.targets
    # Norway 36, Sweden 46 and Denmark 37 for colorectal surgery; 43, 36 and 43 for pancreas.
    assert targets["colorectal"]["pathway"]["surgery"] == 37
    assert targets["pancreas"]["pathway"]["surgery"] == 43
    crc = evaluate(
        version,
        EXAMPLE.model_copy(
            update={
                "site": "colorectal",
                "presentation": ("crc_blood", "crc_iron_deficiency"),
                "days": {
                    S.CONTACT_TO_PHYSICIAN: 3,
                    S.PHYSICIAN_TO_IMAGING: 8,
                    S.IMAGING_TO_REFERRAL: 2,
                },
            }
        ),
    )
    assert crc.trigger.well_founded.countries == ("Sweden",)
    assert crc.trigger.clock_start == 11
    assert {p.site for p in version.compiled.population} == {"lung", "colorectal", "pancreas"}
    pancreas = evaluate(
        version, EXAMPLE.model_copy(update={"site": "pancreas", "presentation": ("panc_imaging",)})
    )
    assert pancreas.trigger.well_founded.countries == ("Denmark", "Norway", "Sweden")
    assert all(lever.grade is EvidenceGrade.ASSUMPTION for lever in pancreas.levers)


def test_the_baseline_has_age_bands_and_the_evaluation_uses_them(version: ModelVersion) -> None:
    young = evaluate(version, EXAMPLE.model_copy(update={"age_band": "50-59"}))
    old = evaluate(version, EXAMPLE.model_copy(update={"age_band": "80-89"}))
    assert young.survival.now > old.survival.now
    baseline = next(c for c in old.contributions if c.term == "baseline")
    assert "age group" in baseline.note
    with pytest.raises(Invalid, match="age_band must be"):
        evaluate(version, EXAMPLE.model_copy(update={"age_band": "60_69"}))


def test_the_spec_must_hold_together() -> None:
    spec = pathway_spec()
    with pytest.raises(Invalid, match="intended_use"):
        compile_spec(spec.model_copy(update={"intended_use": " "}))
    with pytest.raises(Invalid, match="unknown parameter"):
        compile_spec(spec.model_copy(update={"arrows": {"delay_pre": "nothing"}}))
    with pytest.raises(Invalid, match="no baseline"):
        compile_spec(spec.model_copy(update={"sites": ("lung", "liver")}))


def test_the_trigger_fires_and_the_deadlines_count_from_it(version: ModelVersion) -> None:
    result = evaluate(version, EXAMPLE)
    assert result.trigger.suspicion.fired
    assert result.trigger.suspicion.countries == ("Denmark", "Sweden")
    assert result.trigger.well_founded.fired
    assert result.trigger.well_founded.countries == ("Denmark", "Norway", "Sweden")
    assert "Denmark, Norway and Sweden" in result.trigger.note
    # The X-ray on day 14 + 13 = 27 started the clock.
    assert result.trigger.clock_start == 27
    by_label = {d.label: d for d in result.deadlines}
    imaging = by_label["Imaging after suspicion"]
    # Due 6 days after the physician's decision on day 14; done on day 27.
    assert (imaging.due_day, imaging.status, imaging.by) == (20, DeadlineStatus.LATE, 7)
    visit = by_label["First specialist visit"]
    # 4 + 6 days after the trigger: day 37; the visit was on day 27 + 1 + 8 = 36.
    assert (visit.due_day, visit.status, visit.by) == (37, DeadlineStatus.MET, 1)
    workup = by_label["Work-up complete"]
    assert (workup.due_day, workup.status, workup.by) == (59, DeadlineStatus.LATE, 3)
    treatment = by_label["Treatment start"]
    # 44 days after the trigger: day 71; today is day 74.
    assert (treatment.due_day, treatment.status, treatment.by) == (71, DeadlineStatus.OVERDUE, 3)
    assert treatment.countries == ("Denmark", "Norway", "Sweden")


def test_days_behind_are_exact_and_do_not_depend_on_the_toggles(version: ModelVersion) -> None:
    rows = {r.step: r for r in evaluate(version, EXAMPLE).pathway}
    assert (
        rows[S.SYMPTOMS_TO_CONTACT].patient_interval and rows[S.SYMPTOMS_TO_CONTACT].target is None
    )
    assert (
        rows[S.CONTACT_TO_PHYSICIAN].days,
        rows[S.CONTACT_TO_PHYSICIAN].target,
        rows[S.CONTACT_TO_PHYSICIAN].gap,
    ) == (14, 7, 7)
    assert rows[S.PHYSICIAN_TO_IMAGING].gap == 7
    assert rows[S.SPECIALIST_TO_WORKUP].gap == 4
    assert rows[S.WORKUP_TO_TREATMENT].current and rows[S.WORKUP_TO_TREATMENT].gap == 0
    for toggles in ({}, {"pre_trigger": True}, {"finland_residual": False}):
        result = evaluate(version, EXAMPLE.model_copy(update={"toggles": toggles}))
        assert result.days_behind == 20


def test_survival_is_second_graded_and_bounded_by_the_settings(version: ModelVersion) -> None:
    result = evaluate(version, EXAMPLE)
    survival = result.survival
    assert survival.setting == {"finland_residual": True, "pre_trigger": False}
    assert 0 < survival.now <= survival.on_target < 100
    assert set(survival.by_setting) == {
        "finland_residual=on,pre_trigger=on",
        "finland_residual=on,pre_trigger=off",
        "finland_residual=off,pre_trigger=on",
        "finland_residual=off,pre_trigger=off",
    }
    # Without the residual the figures are the Nordic ones, higher.
    assert survival.by_setting["finland_residual=off,pre_trigger=off"].now > survival.now
    assert survival.range_now.low <= survival.now <= survival.range_now.high
    # The days before the trigger count only when asked.
    assert survival.by_setting["finland_residual=on,pre_trigger=on"].now <= survival.now
    grades = {lever.step: lever.grade for lever in result.levers}
    assert grades[S.WORKUP_TO_TREATMENT] is EvidenceGrade.COHORT
    assert grades[S.PHYSICIAN_TO_IMAGING] is EvidenceGrade.ASSUMPTION
    # Education shows as support, never as a lower figure.
    assert any("navigator" in flag for flag in result.flags)
    education = next(c for c in result.contributions if c.term == "direct_education")
    assert not education.applied and education.log_hazard > 0
    assert any("lead time" in w for w in result.warnings)


def test_more_days_beyond_target_never_raise_survival(version: ModelVersion) -> None:
    def now_with(treatment_days: int) -> int:
        days = dict(EXAMPLE.days, **{S.WORKUP_TO_TREATMENT: treatment_days})
        return evaluate(version, EXAMPLE.model_copy(update={"days": days})).survival.now

    figures = [now_with(d) for d in (0, 9, 30, 60, 120)]
    assert figures == sorted(figures, reverse=True)
    # Beyond 16 weeks in total the effect is capped, and said so.
    result = evaluate(
        version,
        EXAMPLE.model_copy(update={"days": dict(EXAMPLE.days, **{S.WORKUP_TO_TREATMENT: 120})}),
    )
    assert any("16 weeks" in w for w in result.warnings)


def test_a_palliative_pathway_has_no_delay_effect(version: ModelVersion) -> None:
    result = evaluate(version, EXAMPLE.model_copy(update={"intent": Intent.PALLIATIVE}))
    assert result.survival.now == result.survival.on_target
    assert result.levers == ()
    assert any("palliative" in w for w in result.warnings)


def test_inputs_are_checked_against_the_terms(version: ModelVersion) -> None:
    with pytest.raises(Invalid, match="site must be"):
        evaluate(version, EXAMPLE.model_copy(update={"site": "liver"}))
    with pytest.raises(Invalid, match="education must be"):
        evaluate(version, EXAMPLE.model_copy(update={"education": "phd"}))
    with pytest.raises(Invalid, match="unknown toggle"):
        evaluate(version, EXAMPLE.model_copy(update={"toggles": {"magic": True}}))
    # A profile that has not reached the trigger has deadlines pending, not overdue.
    early = evaluate(
        version,
        EXAMPLE.model_copy(
            update={"days": {S.CONTACT_TO_PHYSICIAN: 3}, "presentation": ("lung_symptoms_smoker",)}
        ),
    )
    assert early.trigger.clock_start is None
    assert {d.status for d in early.deadlines} <= {
        DeadlineStatus.DUE,
        DeadlineStatus.NOT_APPLICABLE,
    }


# The REST and MCP surfaces.


@pytest.fixture(scope="module")
def client(unreachable_settings: Settings) -> Iterator[TestClient]:
    with serve(unreachable_settings, Overrides()) as client:
        yield client


def _inputs() -> dict[str, Any]:
    return EXAMPLE.model_dump(mode="json")


def test_rest_creates_the_pathway_model_and_evaluates_without_storing_anything(
    client: TestClient,
) -> None:
    project = new_project(client, "Nordic cancer care")
    version = send(client, "POST", f"/projects/{project['id']}/models/pathway", None, 201)
    assert version["version"] == 1
    assert version["spec"]["sites"] == ["lung", "colorectal", "pancreas"]
    models = send(client, "GET", f"/projects/{project['id']}/models")
    assert [m["latest_version"] for m in models] == [1]
    store = resolve(client, MemoryStore)
    before = (
        len(store.runs),
        len(store.snapshots),
        len(store.operators),
        len(store.session_entries),
    )
    result = send(client, "POST", f"/models/{version['model_id']}/evaluate", {"inputs": _inputs()})
    assert result["trigger"]["well_founded"]["fired"] is True
    assert result["days_behind"] == 20
    assert (
        len(store.runs),
        len(store.snapshots),
        len(store.operators),
        len(store.session_entries),
    ) == before
    population = send(client, "GET", f"/models/{version['model_id']}/population")
    assert {p["sex"] for p in population} == {"female", "male"}
    assert send(
        client,
        "POST",
        f"/models/{version['model_id']}/evaluate",
        {"inputs": dict(_inputs(), site="liver")},
        422,
    )


async def test_mcp_lists_evaluates_and_records_an_ordinary_tool_call(
    unreachable_settings: Settings,
) -> None:
    async with mcp_client(unreachable_settings) as (client, seen):
        tools = {tool.name for tool in await client.list_tools()}
        assert {"create_pathway_model", "list_models", "get_model", "evaluate_model"} <= tools
        project = await call(client, "create_project", name="Nordic cancer care")
        session = await call(client, "create_session", project_id=project["id"], title="Models")
        version = await call(
            client, "create_pathway_model", project_id=project["id"], session_id=session["id"]
        )
        result = await call(
            client,
            "evaluate_model",
            model_id=version["model_id"],
            session_id=session["id"],
            inputs=_inputs(),
        )
        assert result["survival"]["now"] <= result["survival"]["on_target"]
        entries = await seen.entries(UUID(session["id"]))
        assert [e.tool_call.tool for e in entries if e.tool_call][-1] == "evaluate_model"
