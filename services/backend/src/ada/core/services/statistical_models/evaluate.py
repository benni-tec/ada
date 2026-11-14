"""The evaluator: a pure function of a version and one profile. No I/O, nothing stored.

Days are counted from the first contact (day 0); the patient interval before it is
context. The trigger (imaging done) ends the third step and starts the clock the deadlines
count from. Survival is the baseline's 5-year relative survival for the profile with the
days beyond target applied on the excess-hazard scale, per setting of the toggles.
"""

import math
from itertools import product

from ada.core.models.errors import Invalid
from ada.core.models.statistical_models import (
    POST_TRIGGER_STEPS,
    PRE_TRIGGER_STEPS,
    STEP_LABELS,
    STEPS,
    TRIGGER_STEP,
    BaselineCell,
    Contribution,
    Deadline,
    DeadlineStatus,
    Evaluation,
    EvaluationInputs,
    EvidenceGrade,
    Figure,
    Form,
    Lever,
    Modality,
    ModelSpec,
    ModelVersion,
    Parameter,
    PathwayRow,
    PathwayStep,
    Per100,
    Range,
    Scale,
    StageResult,
    Survival,
    Trigger,
    TriggerStage,
)

# Hanna et al. found log-linearity between four and 16 weeks of total delay.
MAX_DELAY_DAYS = 16 * 7
TWELVE_WEEKS = 12 * 7
PATHWAY = "pathway"
ANY = "any"

RESIDUAL = "finland_residual"
PRE_TRIGGER = "pre_trigger"


def per100(survival: float) -> Per100:
    return round(100 * survival)


def baseline_cell(
    spec: ModelSpec, site: str, sex: str, age_band: str | None, stage: str | None
) -> BaselineCell | None:
    """The most specific cell for the profile: by age band and stage, then by one of them,
    then the site and sex alone."""
    cells = [c for c in spec.baseline if c.site == site and c.sex == sex]
    for age, stg in ((age_band, stage), (age_band, None), (None, stage), (None, None)):
        for cell in cells:
            if cell.age_band == age and cell.stage == stg:
                return cell
    return None


def arrow(spec: ModelSpec, *keys: str) -> Parameter | None:
    """The parameter of the most specific arrow among `keys`."""
    for key in keys:
        name = spec.arrows.get(key)
        if name is not None:
            return spec.parameters[name]
    return None


def target(
    compiled_targets: dict[str, dict[str, dict[str, int]]],
    site: str,
    step: PathwayStep | None,
    modality: Modality,
) -> int | None:
    by_step = compiled_targets.get(site, {})
    by_modality = by_step.get(step.value if step else PATHWAY, {})
    days = by_modality.get(modality.value, by_modality.get(ANY))
    return days


def to_excess(parameter: Parameter, cell: BaselineCell | None) -> tuple[float, str | None]:
    """A hazard ratio on the excess scale. An overall-mortality HR is diluted towards 1 by
    other-cause deaths; with the cell's excess share p it becomes 1 + (HR - 1) / p."""
    hr = parameter.estimate
    if parameter.scale is not Scale.OVERALL:
        return hr, None
    if cell is None or cell.excess_share is None:
        return (
            hr,
            f"{parameter.name}: no excess share is loaded for the baseline, so the "
            f"overall-mortality HR is used unconverted",
        )
    return 1 + (hr - 1) / cell.excess_share, None


def delay_log_hazard(
    parameter: Parameter | None,
    cell: BaselineCell | None,
    total_days: int,
    pathway_target: int | None,
) -> tuple[float, list[str]]:
    """The log hazard ratio for a trigger-to-treatment delay of `total_days` against the
    pathway target, and the warnings it raises. Days at or under target have no effect:
    the model never claims a benefit from being faster than the standard."""
    warnings: list[str] = []
    if parameter is None or pathway_target is None:
        return 0.0, warnings
    capped = min(total_days, MAX_DELAY_DAYS)
    if total_days > MAX_DELAY_DAYS:
        warnings.append(
            f"The delay of {total_days} days exceeds 16 weeks, beyond which the published effect "
            f"is not known; it is capped at 16 weeks"
        )
    excess = max(0, capped - pathway_target)
    hr, warning = to_excess(parameter, cell)
    if warning:
        warnings.append(warning)
    if parameter.form is Form.PER_4_WEEKS:
        return math.log(hr) * excess / 28, warnings
    if parameter.form is Form.BEYOND_12_WEEKS:
        return (math.log(hr) if capped > TWELVE_WEEKS else 0.0), warnings
    if parameter.form is Form.HAZARD_RATIO:
        return (math.log(hr) if excess > 0 else 0.0), warnings
    raise Invalid(f"{parameter.name} has form {parameter.form}, which is not a delay effect")


def pre_trigger_log_hazard(parameter: Parameter | None, days_behind: int) -> float:
    if parameter is None or days_behind <= 0:
        return 0.0
    if parameter.form is not Form.PER_DAY:
        raise Invalid(f"{parameter.name} has form {parameter.form}, which is not a per-day effect")
    return math.log1p(parameter.estimate) * days_behind


def _validate(spec: ModelSpec, inputs: EvaluationInputs) -> None:
    if inputs.site not in spec.sites:
        raise Invalid(f"site must be one of {', '.join(spec.sites)}, not {inputs.site!r}")
    for term in spec.terms:
        value = getattr(inputs, term.name, None)
        if value is not None and value not in term.levels:
            raise Invalid(f"{term.name} must be one of {', '.join(term.levels)}, not {value!r}")
    for step, days in inputs.days.items():
        if days < 0:
            raise Invalid(f"days in {step.value} must not be negative")
    for name in inputs.toggles:
        if name not in {t.name for t in spec.toggles}:
            raise Invalid(f"unknown toggle {name!r}")
    if baseline_cell(spec, inputs.site, inputs.sex, None, None) is None:
        raise Invalid(f"the version has no baseline for {inputs.site} ({inputs.sex})")


class _Pathway:
    """The days per step as given, with what has been completed, what is current, and the
    day each step ended, counted from the first contact."""

    def __init__(self, inputs: EvaluationInputs) -> None:
        given = [s for s in STEPS if s in inputs.days]
        self.days = {s: inputs.days[s] for s in given}
        self.current = given[-1] if given else None
        self.completed = set(given[:-1])
        self.today = sum(
            d for s, d in self.days.items() if s is not PathwayStep.SYMPTOMS_TO_CONTACT
        )

    def end_of(self, step: PathwayStep) -> int | None:
        """The day a completed step ended."""
        if step not in self.completed:
            return None
        return sum(
            self.days[s]
            for s in STEPS
            if s in self.days
            and s is not PathwayStep.SYMPTOMS_TO_CONTACT
            and STEPS.index(s) <= STEPS.index(step)
        )

    def started(self, step: PathwayStep) -> bool:
        return step in self.days


def _trigger(spec: ModelSpec, inputs: EvaluationInputs, pathway: _Pathway) -> Trigger:
    results = {}
    for stage in TriggerStage:
        met = [
            c
            for c in spec.criteria
            if c.site == inputs.site and c.stage is stage and c.id in inputs.presentation
        ]
        countries = tuple(sorted({country for c in met for country in c.countries}))
        results[stage] = StageResult(
            stage=stage, fired=bool(met), countries=countries, criteria=tuple(c.text for c in met)
        )
    well_founded = results[TriggerStage.WELL_FOUNDED]
    clock_start = pathway.end_of(TRIGGER_STEP) if well_founded.fired else None
    if well_founded.fired:
        where = " and ".join(well_founded.countries)
        note = (
            f"This presentation would start a pathway in {where}. "
            "Finland has no national trigger and no standard times."
        )
    elif results[TriggerStage.SUSPICION].fired:
        note = (
            "The suspicion criteria are met: imaging decides whether the pathway starts. "
            "Finland has no national trigger."
        )
    else:
        note = "No pathway criterion is met by the presentation given."
    return Trigger(
        suspicion=results[TriggerStage.SUSPICION],
        well_founded=well_founded,
        clock_start=clock_start,
        note=note,
    )


def _status(due: int | None, completed_on: int | None, today: int) -> tuple[DeadlineStatus, int]:
    if due is None:
        return DeadlineStatus.NOT_APPLICABLE, 0
    if completed_on is not None:
        late = completed_on - due
        return (DeadlineStatus.LATE, late) if late > 0 else (DeadlineStatus.MET, -late)
    left = due - today
    return (DeadlineStatus.DUE, left) if left >= 0 else (DeadlineStatus.OVERDUE, -left)


def _countries(
    spec: ModelSpec, site: str, step: PathwayStep | None, modality: Modality
) -> tuple[str, ...]:
    countries: set[str] = set()
    for t in spec.targets:
        if t.site == site and t.step is step and t.modality in (None, modality):
            countries.update(t.days_by_country)
    return tuple(sorted(countries))


def _deadlines(
    spec: ModelSpec,
    targets: dict[str, dict[str, dict[str, int]]],
    inputs: EvaluationInputs,
    pathway: _Pathway,
    trigger: Trigger,
) -> tuple[Deadline, ...]:
    site, modality = inputs.site, inputs.modality
    t = {step: target(targets, site, step, modality) for step in STEPS}
    whole = target(targets, site, None, modality)
    deadlines: list[Deadline] = []

    imaging_target = t[PathwayStep.PHYSICIAN_TO_IMAGING]
    physician_seen = pathway.end_of(PathwayStep.CONTACT_TO_PHYSICIAN)
    if trigger.suspicion.fired and imaging_target is not None:
        due = physician_seen + imaging_target if physician_seen is not None else None
        status, by = _status(due, pathway.end_of(PathwayStep.PHYSICIAN_TO_IMAGING), pathway.today)
        deadlines.append(
            Deadline(
                label="Imaging after suspicion",
                rule=f"within {imaging_target} days of the physician's referral decision",
                countries=_countries(spec, site, PathwayStep.PHYSICIAN_TO_IMAGING, modality),
                due_day=due,
                status=status,
                by=by,
            )
        )

    # The deadlines count from the trigger, not from when each step happened to start, so
    # a late step does not move the next deadline.
    start = trigger.clock_start
    cumulative = t[PathwayStep.IMAGING_TO_REFERRAL] or 0
    for step, label in (
        (PathwayStep.REFERRAL_TO_SPECIALIST, "First specialist visit"),
        (PathwayStep.SPECIALIST_TO_WORKUP, "Work-up complete"),
    ):
        cumulative += t[step] or 0
        due = start + cumulative if start is not None and t[step] is not None else None
        status, by = _status(due, pathway.end_of(step), pathway.today)
        deadlines.append(
            Deadline(
                label=label,
                rule=f"{cumulative} days after the trigger",
                countries=_countries(spec, site, step, modality),
                due_day=due,
                status=status,
                by=by,
            )
        )

    due = start + whole if start is not None and whole is not None else None
    status, by = _status(due, pathway.end_of(PathwayStep.WORKUP_TO_TREATMENT), pathway.today)
    deadlines.append(
        Deadline(
            label="Treatment start",
            rule=f"{whole} days after the trigger"
            if whole is not None
            else "no standard time loaded",
            countries=_countries(spec, site, None, modality),
            due_day=due,
            status=status,
            by=by,
        )
    )
    return tuple(deadlines)


def _rows(
    spec: ModelSpec,
    targets: dict[str, dict[str, dict[str, int]]],
    inputs: EvaluationInputs,
    pathway: _Pathway,
) -> tuple[PathwayRow, ...]:
    rows = []
    for step in STEPS:
        days = pathway.days.get(step)
        t = target(targets, inputs.site, step, inputs.modality)
        gap = max(0, days - t) if days is not None and t is not None else 0
        rows.append(
            PathwayRow(
                step=step,
                label=STEP_LABELS[step],
                days=days,
                target=t,
                gap=gap,
                countries=_countries(spec, inputs.site, step, inputs.modality),
                patient_interval=step is PathwayStep.SYMPTOMS_TO_CONTACT,
                current=step is pathway.current,
            )
        )
    return tuple(rows)


def _projected(
    pathway: _Pathway,
    typical: dict[PathwayStep, int],
    targets: dict[PathwayStep, int | None],
    on_target: set[PathwayStep],
) -> int:
    """Trigger-to-treatment days once the pathway is complete: completed steps as they
    were, the current step at least as long as it has been, the rest at the typical days
    (or at target for the steps in `on_target`)."""
    total = 0
    for step in POST_TRIGGER_STEPS:
        t = targets.get(step)
        rest = t if step in on_target and t is not None else typical.get(step, t or 0)
        if step in pathway.completed:
            total += pathway.days[step]
        elif step is pathway.current:
            total += max(pathway.days[step], rest)
        else:
            total += rest
    return total


def evaluate(version: ModelVersion, inputs: EvaluationInputs) -> Evaluation:
    spec = version.spec
    _validate(spec, inputs)
    pathway = _Pathway(inputs)
    trigger = _trigger(spec, inputs, pathway)
    deadlines = _deadlines(spec, version.compiled.targets, inputs, pathway, trigger)
    rows = _rows(spec, version.compiled.targets, inputs, pathway)
    days_behind = sum(r.gap for r in rows)
    warnings: list[str] = list(spec.cautions)

    cell = baseline_cell(spec, inputs.site, inputs.sex, inputs.age_band, inputs.stage)
    assert cell is not None
    if inputs.stage is not None and cell.stage is None:
        warnings.append(
            "No stage-specific baseline is loaded for this site, so the all-stage figure is used"
        )
    base_hazard = -math.log(cell.survival)

    step_targets = {
        s: target(version.compiled.targets, inputs.site, s, inputs.modality) for s in STEPS
    }
    whole = target(version.compiled.targets, inputs.site, None, inputs.modality)
    typical = spec.comparison.days.get(inputs.site, {})
    curative = inputs.intent is not inputs.intent.PALLIATIVE
    delay = (
        arrow(
            spec, f"delay_post:{inputs.site}:{inputs.modality.value}", f"delay_post:{inputs.site}"
        )
        if curative
        else None
    )
    if not curative:
        warnings.append(
            "A palliative pathway: the delay effects, which were estimated for curative treatment, "
            "are not applied"
        )
    pre = arrow(spec, "delay_pre")
    pre_days_behind = sum(r.gap for r in rows if r.step in PRE_TRIGGER_STEPS)
    residuals = {(p.site, p.sex): p.residual for p in version.compiled.population}
    residual = residuals.get((inputs.site, inputs.sex), 1.0)

    def survival(setting: dict[str, bool], on_target: set[PathwayStep]) -> tuple[float, list[str]]:
        total = _projected(pathway, typical, step_targets, on_target)
        log_hr, notes = delay_log_hazard(delay, cell, total, whole)
        if setting.get(PRE_TRIGGER):
            log_hr += pre_trigger_log_hazard(pre, pre_days_behind)
        hazard = base_hazard * math.exp(log_hr)
        if setting.get(RESIDUAL):
            hazard *= residual
        return math.exp(-hazard), notes

    headline = {t.name: inputs.toggles.get(t.name, t.default) for t in spec.toggles}
    by_setting: dict[str, Figure] = {}
    for values in product((True, False), repeat=len(spec.toggles)):
        setting = {t.name: v for t, v in zip(spec.toggles, values, strict=True)}
        now, _ = survival(setting, set())
        on, _ = survival(setting, set(POST_TRIGGER_STEPS))
        key = ",".join(f"{name}={'on' if v else 'off'}" for name, v in setting.items())
        by_setting[key] = Figure(now=per100(now), on_target=per100(on))
    now_value, notes = survival(headline, set())
    on_value, _ = survival(headline, set(POST_TRIGGER_STEPS))
    warnings.extend(notes)
    nows = [f.now for f in by_setting.values()] or [per100(now_value)]
    ons = [f.on_target for f in by_setting.values()] or [per100(on_value)]
    figure = Survival(
        now=per100(now_value),
        on_target=per100(on_value),
        by_setting=by_setting,
        range_now=Range(low=min(nows), high=max(nows)),
        range_on_target=Range(low=min(ons), high=max(ons)),
        setting=headline,
    )

    levers: list[Lever] = []
    if curative and delay is not None:
        for step in POST_TRIGGER_STEPS:
            if step in pathway.completed:
                continue
            alone, _ = survival(headline, {step})
            gain = per100(alone) - figure.now
            levers.append(
                Lever(
                    step=step,
                    label=STEP_LABELS[step],
                    gain=gain,
                    grade=delay.provenance.grade,
                    text=f"{STEP_LABELS[step]} on target ({step_targets[step]} days): "
                    f"{delay.provenance.source}",
                )
            )
    if curative and pre_days_behind > 0 and pre is not None:
        # What those days are worth under the pre-trigger assumption: the figure with them
        # counted against the figure as if they had been on target.
        counted, _ = survival(dict(headline, **{PRE_TRIGGER: True}), set())
        recovered, _ = survival(dict(headline, **{PRE_TRIGGER: False}), set())
        levers.append(
            Lever(
                step=TRIGGER_STEP,
                label=f"The {pre_days_behind} days lost before the trigger",
                gain=per100(recovered) - per100(counted),
                grade=EvidenceGrade.ASSUMPTION,
                text="Already spent for this patient; a system lever (appointment access, "
                "nurse-ordered imaging). Their survival effect is an assumption, and part of "
                "it is lead time.",
            )
        )
    levers.sort(key=lambda lever: -lever.gain)

    flags = tuple(f.action for f in spec.flags if getattr(inputs, f.term, None) == f.level)

    direct = arrow(
        spec,
        f"direct_education:{inputs.site}:{inputs.sex}",
        f"direct_education:{inputs.site}",
        "direct_education",
    )
    stage_or = arrow(spec, f"stage_education:{inputs.site}:{inputs.sex}", "stage_education")
    contributions = [
        Contribution(
            term="baseline",
            log_hazard=math.log(base_hazard),
            applied=True,
            note=f"{cell.provenance.source}: 5-year relative survival {cell.survival:.3f}",
        ),
        Contribution(
            term="delay_post",
            log_hazard=delay_log_hazard(
                delay, cell, _projected(pathway, typical, step_targets, set()), whole
            )[0],
            applied=delay is not None,
            note="days from the trigger to treatment beyond the target",
        ),
        Contribution(
            term="delay_pre",
            log_hazard=pre_trigger_log_hazard(pre, pre_days_behind),
            applied=bool(headline.get(PRE_TRIGGER)),
            note="days before the trigger beyond target; a toggle",
        ),
        Contribution(
            term="finland_residual",
            log_hazard=math.log(residual) if residual > 0 else 0.0,
            applied=bool(headline.get(RESIDUAL)),
            note="what the days do not explain of the Finnish shortfall; a toggle",
        ),
        Contribution(
            term="direct_education",
            log_hazard=math.log(direct.estimate)
            if direct is not None and inputs.education == "basic"
            else 0.0,
            applied=False,
            note="held at the population mix in patient figures; analyst view only",
        ),
        Contribution(
            term="stage_education",
            log_hazard=0.0,
            applied=False,
            note="skipped: no stage-specific baseline is loaded"
            if cell.stage is None
            else "skipped: the stage is given"
            if stage_or
            else "no parameter",
        ),
    ]

    return Evaluation(
        model_id=version.model_id,
        version=version.version,
        trigger=trigger,
        deadlines=deadlines,
        pathway=rows,
        days_behind=days_behind,
        survival=figure,
        levers=tuple(levers),
        flags=flags,
        warnings=tuple(dict.fromkeys(warnings)),
        contributions=tuple(contributions),
    )
