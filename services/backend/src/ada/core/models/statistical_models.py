"""Statistical models: a versioned model built from published figures, each with its
provenance, evaluated on one profile at a time. Evaluations are computed, never stored.

The first kind is the patient pathway model (docs/superpowers/plans/2026-11-14-statistical-
models-grounding.md): whether a presentation would start a Nordic fast-track cancer
pathway, when each step is due, how many days the pathway is behind target, and, second
and graded, the 5-year survival associated with the difference.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Discriminator, Tag

from ada.core.models.actors import Actor
from ada.core.models.base import DomainModel, Id

# People out of 100: every patient-facing survival figure is one of these.
type Per100 = int


class EvidenceGrade(StrEnum):
    # A national pathway standard: criteria or times.
    STANDARD = "standard"
    META_ANALYSIS = "meta_analysis"
    COHORT = "cohort"
    REGISTRY = "registry"
    ASSUMPTION = "assumption"


class Scale(StrEnum):
    """What a parameter is measured on. Hazard ratios on overall mortality are converted to
    the excess scale at build (Compiled.parameters), the others are used as they are."""

    EXCESS = "excess"
    CAUSE_SPECIFIC = "cause_specific"
    OVERALL = "overall"
    ODDS_RATIO = "odds_ratio"
    PER_DAY = "per_day"
    DAYS = "days"
    SURVIVAL = "survival"
    # A ratio of two durations: days without a standardised pathway over days with one.
    RATIO = "ratio"


class Citation(DomainModel):
    """Where a figure comes from: the citation, the passage it was checked against, and
    the evidence grade shown beside it."""

    source: str
    passage: str
    grade: EvidenceGrade
    url: str | None = None
    country: str | None = None
    # When the document is registered as an ADA source: its id, so the lineage shows it.
    source_id: str | None = None
    # When the figure was read from an ADA operator: its id and the run it was read in.
    operator_id: str | None = None
    run_id: str | None = None


class Form(StrEnum):
    """How a parameter enters the model."""

    # A hazard ratio per four weeks of delay (Hanna).
    PER_4_WEEKS = "per_4_weeks"
    # A hazard ratio that applies once the delay exceeds twelve weeks (Heiden).
    BEYOND_12_WEEKS = "beyond_12_weeks"
    # A per-day fatality rate: the hazard ratio is (1 + rate) ** days (Sud).
    PER_DAY = "per_day"
    HAZARD_RATIO = "hazard_ratio"
    ODDS_RATIO = "odds_ratio"
    VALUE = "value"


class Parameter(DomainModel):
    name: str
    estimate: float
    ci_low: float | None = None
    ci_high: float | None = None
    scale: Scale
    form: Form = Form.VALUE
    provenance: Citation


class PathwayStep(StrEnum):
    """The seven intervals of a pathway, in order, from the first symptoms to the start of
    treatment. The first is the patient interval; the trigger (imaging done) ends the
    third; the clock the deadlines count from starts there."""

    SYMPTOMS_TO_CONTACT = "symptoms_to_contact"
    CONTACT_TO_PHYSICIAN = "contact_to_physician"
    PHYSICIAN_TO_IMAGING = "physician_to_imaging"
    IMAGING_TO_REFERRAL = "imaging_to_referral"
    REFERRAL_TO_SPECIALIST = "referral_to_specialist"
    SPECIALIST_TO_WORKUP = "specialist_to_workup"
    WORKUP_TO_TREATMENT = "workup_to_treatment"


STEPS: tuple[PathwayStep, ...] = tuple(PathwayStep)
TRIGGER_STEP = PathwayStep.PHYSICIAN_TO_IMAGING
PRE_TRIGGER_STEPS = (PathwayStep.CONTACT_TO_PHYSICIAN, PathwayStep.PHYSICIAN_TO_IMAGING)
POST_TRIGGER_STEPS = (
    PathwayStep.IMAGING_TO_REFERRAL,
    PathwayStep.REFERRAL_TO_SPECIALIST,
    PathwayStep.SPECIALIST_TO_WORKUP,
    PathwayStep.WORKUP_TO_TREATMENT,
)

# The diagnostic interval of the Danish before-and-after study (first presentation to
# diagnosis): the steps the effect of having no standardised pathway applies to.
DIAGNOSTIC_STEPS = (
    PathwayStep.CONTACT_TO_PHYSICIAN,
    PathwayStep.PHYSICIAN_TO_IMAGING,
    PathwayStep.IMAGING_TO_REFERRAL,
    PathwayStep.REFERRAL_TO_SPECIALIST,
    PathwayStep.SPECIALIST_TO_WORKUP,
)

# The parameter that holds that effect: days without a standardised pathway over days with.
NO_PATHWAY = "no_pathway_ratio"

STEP_LABELS: dict[PathwayStep, str] = {
    PathwayStep.SYMPTOMS_TO_CONTACT: "Symptoms → first contact",
    PathwayStep.CONTACT_TO_PHYSICIAN: "First contact → physician",
    PathwayStep.PHYSICIAN_TO_IMAGING: "Physician → imaging done",
    PathwayStep.IMAGING_TO_REFERRAL: "Imaging → pathway referral",
    PathwayStep.REFERRAL_TO_SPECIALIST: "Referral → first specialist visit",
    PathwayStep.SPECIALIST_TO_WORKUP: "First visit → work-up complete",
    PathwayStep.WORKUP_TO_TREATMENT: "Work-up complete → treatment start",
}


class TriggerStage(StrEnum):
    # Sends the patient to imaging (Sweden's "misstanke").
    SUSPICION = "suspicion"
    # Starts the pathway and its clock ("begrunnet mistanke", "välgrundad misstanke").
    WELL_FOUNDED = "well_founded"


class Criterion(DomainModel):
    """One entry of a national pathway's criteria; the countries whose standard lists it."""

    id: str
    site: str
    stage: TriggerStage
    text: str
    countries: tuple[str, ...]
    provenance: Citation


class Modality(StrEnum):
    SURGERY = "surgery"
    RADIOTHERAPY = "radiotherapy"
    DRUGS = "drugs"


class TargetTime(DomainModel):
    """A step's standard time in each country that defines it. The target is their median
    (Compiled.targets). `step` None is the whole pathway, trigger to treatment start."""

    site: str
    step: PathwayStep | None
    # None: every modality.
    modality: Modality | None = None
    days_by_country: dict[str, int]
    provenance: Citation
    # The documents of the other countries in `days_by_country`.
    other_sources: tuple[Citation, ...] = ()


class BaselineCell(DomainModel):
    """5-year relative survival for a profile in the baseline population (the Nordic
    level). `age_band` or `stage` None: all of them."""

    site: str
    sex: str
    age_band: str | None = None
    stage: str | None = None
    # 0 to 1.
    survival: float
    # The share of the hazard that is excess hazard, for converting overall-mortality HRs;
    # None: not loaded, so overall HRs are used unconverted, with a warning.
    excess_share: float | None = None
    provenance: Citation


class ComparisonPopulation(DomainModel):
    """What the model is compared with: a country's observed survival per site and sex,
    and its typical days per step, for the residual and the population view."""

    country: str
    # (site, sex) -> 5-year relative survival, 0 to 1.
    survival: dict[str, float]
    # site -> step -> typical days.
    days: dict[str, dict[PathwayStep, int]]
    provenance: Citation
    # "<site>:<sex>:<education level>" -> observed 5-year survival, for the education check;
    # with the citation it comes from.
    survival_by_education: dict[str, float] = {}
    education_provenance: Citation | None = None


class Toggle(DomainModel):
    name: str
    label: str
    default: bool
    about: str


class Flag(DomainModel):
    """An offer of support shown when a term has a level, e.g. a navigator after basic
    education. Never a risk label."""

    term: str
    level: str
    action: str
    provenance: Citation


class Term(DomainModel):
    name: str
    levels: tuple[str, ...]
    reference: str
    display: Literal["patient", "analyst"] = "patient"


class ModelSpec(DomainModel):
    """Everything a version is built from. Validated when a version is created
    (StatisticalModelService.create)."""

    # The model kind this spec is for (ada.core.services.statistical_models.kinds);
    # ModelVersion.spec is a union tagged by it.
    kind: Literal["patient_pathway"] = "patient_pathway"
    outcome: str
    structure: Literal["relative_survival_dag"] = "relative_survival_dag"
    sites: tuple[str, ...]
    terms: tuple[Term, ...]
    criteria: tuple[Criterion, ...]
    targets: tuple[TargetTime, ...]
    baseline: tuple[BaselineCell, ...]
    parameters: dict[str, Parameter]
    # Each arrow of the DAG names exactly one parameter. Keys: "delay_post:<site>:<modality>"
    # (the most specific of "delay_post:<site>:<modality>", "delay_post:<site>" is used),
    # "delay_pre", "stage_education:<site>:<sex>" (or "stage_education"),
    # "direct_education:<site>:<sex>" (or "direct_education").
    arrows: dict[str, str]
    comparison: ComparisonPopulation
    toggles: tuple[Toggle, ...]
    flags: tuple[Flag, ...]
    intended_use: str
    # What the model is not: lead time, the waiting-time paradox, where the effects come from.
    cautions: tuple[str, ...] = ()


class PopulationFigure(DomainModel):
    """Per site and sex: the baseline, the baseline with the comparison country's days,
    and that country's observed survival. The residual is what the days do not explain."""

    site: str
    sex: str
    baseline: Per100
    timing_adjusted: Per100
    observed: Per100
    # The factor on the excess hazard that takes the timing-adjusted figure to the
    # observed one; 1 when timing explains everything.
    residual: float
    # How the timing adjustment was made, e.g. which rate over how many extra days.
    note: str


class StepTime(DomainModel):
    """One step of one site's pathway, four ways: the Nordic standard, the days expected in
    Finland without a standardised pathway, Finland's published typical days, and the
    median of the model's cases. Each is None where there is none."""

    site: str
    step: PathwayStep
    label: str
    nordic: int | None
    expected: float | None
    published: int | None
    measured: float | None
    # How many of the model's cases have this step's days.
    cases: int


class ValidationCheck(DomainModel):
    """One check of the build against a figure the model was not built from."""

    name: str
    expected: float
    predicted: float
    note: str


class Compiled(DomainModel):
    """What the build derived from the spec."""

    kind: Literal["patient_pathway"] = "patient_pathway"
    # site -> step (or "pathway") -> modality (or "any") -> median days.
    targets: dict[str, dict[str, dict[str, int]]]
    # The parameters as built. Overall-mortality HRs are converted to the excess scale per
    # profile, with the excess share of the profile's own baseline cell (evaluate.to_excess).
    parameters: dict[str, Parameter]
    population: tuple[PopulationFigure, ...]
    validation: tuple[ValidationCheck, ...] = ()
    warnings: tuple[str, ...] = ()


class StatisticalModel(DomainModel):
    id: Id
    project_id: Id
    name: str
    description: str
    kind: str
    latest_version: int
    # The case type it runs on (ada.core.models.cases); None for a model on no case type.
    case_type_id: Id | None = None
    # Run on every save of a case of its type; otherwise only on request. Never backfilled.
    auto_run: bool = False
    created_by: Actor
    created_at: datetime
    # When its latest version was made.
    updated_at: datetime | None = None


class TrialMatcherSpec(DomainModel):
    """The trial matcher: the recruiting trials a case could be discussed for. It filters on
    the case's cancer group only, a topic match and not an eligibility judgement; sex and
    age limits are shown beside each trial, never used to leave one out; trials are sorted
    by distance. It reads its data steps whenever it runs, so it is as current as they are."""

    kind: Literal["trial_matcher"] = "trial_matcher"
    # The trials data step (Felix's `case_trials`, docs/trials.md).
    operator_id: str
    # The step that names each wellbeing services county's distance city (`county_cities`);
    # without it, or for a county it does not list, distances are from Helsinki.
    county_operator_id: str | None = None
    # A case's site -> the trials data's cancer group.
    groups: dict[str, str] = {
        "lung": "lung",
        "colorectal": "colorectal",
        "pancreas": "pancreas",
    }
    intended_use: str = (
        "Educational: lists recruiting Nordic trials of a synthetic case's cancer group, "
        "nearest first, to discuss with an oncologist. Not an eligibility decision; never "
        "patient data."
    )
    cautions: tuple[str, ...] = (
        "Filtered on cancer group only; sex and age limits are shown, not applied.",
        "The eligibility text is the registry's, as written, and is not judged.",
        "Recruiting means the registry's site status, which lags.",
    )


class TrialCompiled(DomainModel):
    """A trial matcher's build: nothing to precompute, since it reads its data steps when it
    runs."""

    kind: Literal["trial_matcher"] = "trial_matcher"
    warnings: tuple[str, ...] = ()


def _kind(value: Any) -> str:
    """The kind a spec or a build is for; versions stored before kinds had none."""
    if isinstance(value, dict):
        return value.get("kind", "patient_pathway")
    return getattr(value, "kind", "patient_pathway")


# Each kind's spec and build: the survival DAG for the patient pathway model, the pinned
# trials for the trial matcher.
type AnySpec = Annotated[
    Annotated[ModelSpec, Tag("patient_pathway")]
    | Annotated[TrialMatcherSpec, Tag("trial_matcher")],
    Discriminator(_kind),
]
type AnyCompiled = Annotated[
    Annotated[Compiled, Tag("patient_pathway")] | Annotated[TrialCompiled, Tag("trial_matcher")],
    Discriminator(_kind),
]


class ModelVersion(DomainModel):
    """Immutable; a change makes a new version."""

    id: Id
    model_id: Id
    version: int
    spec: AnySpec
    compiled: AnyCompiled
    created_by: Actor
    created_at: datetime


class Intent(StrEnum):
    CURATIVE = "curative"
    PALLIATIVE = "palliative"
    UNKNOWN = "unknown"


class EvaluationInputs(DomainModel):
    """One profile. Days are the days spent in each step so far; a step left out has not
    started. Synthetic profiles only: the platform is not for patient data."""

    site: str
    sex: str
    age_band: str | None = None
    education: str | None = None
    route: str | None = None
    stage: str | None = None
    intent: Intent = Intent.UNKNOWN
    modality: Modality = Modality.SURGERY
    # Ids of the criteria the presentation meets.
    presentation: tuple[str, ...] = ()
    days: dict[PathwayStep, int] = {}
    # Treatment has started: the last step given is complete, not current.
    treatment_started: bool = False
    # Toggle name -> on; a toggle left out takes its default.
    toggles: dict[str, bool] = {}


class StageResult(DomainModel):
    stage: TriggerStage
    fired: bool
    countries: tuple[str, ...]
    criteria: tuple[str, ...]


class Trigger(DomainModel):
    suspicion: StageResult
    well_founded: StageResult
    # The day, counted from the first contact, the pathway clock started; None: not yet.
    clock_start: int | None
    note: str


class DeadlineStatus(StrEnum):
    MET = "met"
    LATE = "late"
    DUE = "due"
    OVERDUE = "overdue"
    NOT_APPLICABLE = "not_applicable"


class Deadline(DomainModel):
    label: str
    # The rule, e.g. "Norway: 7 days after the referral".
    rule: str
    countries: tuple[str, ...]
    # Days from the first contact.
    due_day: int | None
    status: DeadlineStatus
    # Days late or early, or days until due; 0 when due today.
    by: int


class PathwayRow(DomainModel):
    step: PathwayStep
    label: str
    days: int | None
    target: int | None
    # The days expected in Finland without a standardised pathway: the target times the
    # no-pathway ratio on a diagnostic step, the target on the others; None without one.
    expected: float | None = None
    gap: int
    countries: tuple[str, ...]
    patient_interval: bool
    current: bool


class Figure(DomainModel):
    now: Per100
    on_target: Per100


class Range(DomainModel):
    low: Per100
    high: Per100


class Survival(DomainModel):
    now: Per100
    on_target: Per100
    # Every combination of the toggles, keyed "name=on,name=off".
    by_setting: dict[str, Figure]
    range_now: Range
    range_on_target: Range
    # The setting the headline figures are for.
    setting: dict[str, bool]


class Lever(DomainModel):
    step: PathwayStep
    label: str
    # People out of 100, on the headline setting.
    gain: Per100
    grade: EvidenceGrade
    text: str


class Contribution(DomainModel):
    """A term's effect on the log cumulative excess hazard, for the analyst view."""

    term: str
    log_hazard: float
    applied: bool
    note: str


class Evaluation(DomainModel):
    model_id: Id
    version: int
    trigger: Trigger
    deadlines: tuple[Deadline, ...]
    pathway: tuple[PathwayRow, ...]
    days_behind: int
    survival: Survival
    levers: tuple[Lever, ...]
    flags: tuple[str, ...]
    warnings: tuple[str, ...]
    contributions: tuple[Contribution, ...]


type Json = dict[str, Any]
