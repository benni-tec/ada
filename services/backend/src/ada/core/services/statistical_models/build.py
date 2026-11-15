"""The build: what a version derives from its spec once. The median target per step,
overall-mortality HRs converted to the excess scale, and the population view with the
residual per site and sex."""

import math
from statistics import median

from ada.core.models.analysis import Rows
from ada.core.models.errors import Invalid
from ada.core.models.statistical_models import (
    STEPS,
    Compiled,
    Form,
    Modality,
    ModelSpec,
    PopulationFigure,
    TriggerStage,
    ValidationCheck,
)
from ada.core.services.statistical_models.evaluate import (
    ANY,
    PATHWAY,
    baseline_cell,
    per100,
    target,
    to_excess,
)

PARAMETER_COLUMNS = ("name", "estimate", "ci_low", "ci_high", "source_id", "passage", "found")


def _found(value: object) -> bool:
    """The `found` column as a truth value: a boolean, or the text true/false. Anything
    else is refused rather than read as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise Invalid(f"found must be true or false, not {value!r}")


def _number(value: object) -> float | None:
    return None if value is None else float(str(value))


def read_parameters(spec: ModelSpec, rows: Rows, operator_id: str, run_id: str) -> ModelSpec:
    """The spec with its parameters taken from an operator's rows: one row per parameter,
    with the estimate, the interval, the source and the passage, and `found`, whether the
    passage is in the source as fetched. Every parameter cited to a registered source must
    have a found row; the others (assumptions with no source) keep their figures."""
    names = [c.name for c in rows.columns]
    missing = [c for c in PARAMETER_COLUMNS if c not in names]
    if missing:
        raise Invalid(f"operator {operator_id} lacks the columns {', '.join(missing)}")
    parameters = dict(spec.parameters)
    read: set[str] = set()
    for values in rows.rows:
        row = dict(zip(names, values, strict=True))
        name = str(row["name"])
        if name not in parameters:
            raise Invalid(f"operator {operator_id} has a row for an unknown parameter: {name}")
        if name in read:
            raise Invalid(f"operator {operator_id} has two rows for {name}")
        if not _found(row["found"]):
            raise Invalid(f"the passage for {name} is not in its source as fetched")
        cited = parameters[name].provenance.source_id
        if cited and str(row["source_id"]) != cited:
            raise Invalid(
                f"operator {operator_id} cites {row['source_id']} for {name}, "
                f"whose citation is source {cited}"
            )
        if row["estimate"] is None:
            raise Invalid(f"operator {operator_id} has no estimate for {name}")
        p = parameters[name]
        parameters[name] = p.model_copy(
            update={
                "estimate": _number(row["estimate"]),
                "ci_low": _number(row["ci_low"]),
                "ci_high": _number(row["ci_high"]),
                "provenance": p.provenance.model_copy(
                    update={
                        "passage": str(row["passage"]),
                        "source_id": str(row["source_id"]),
                        "operator_id": operator_id,
                        "run_id": run_id,
                    }
                ),
            }
        )
        read.add(name)
    unread = sorted(
        n for n, p in spec.parameters.items() if p.provenance.source_id and n not in read
    )
    if unread:
        raise Invalid(f"operator {operator_id} has no row for {', '.join(unread)}")
    return spec.model_copy(update={"parameters": parameters})


MAX_TOGGLES = 4


def validate(spec: ModelSpec) -> None:
    """Invalid when the spec does not hold together."""
    if not spec.intended_use.strip():
        raise Invalid("intended_use must say what the model is for")
    if not spec.sites:
        raise Invalid("a model needs at least one site")
    for site in spec.sites:
        sexes = {c.sex for c in spec.baseline if c.site == site}
        if not sexes:
            raise Invalid(f"no baseline for {site}")
    for cell in spec.baseline:
        if cell.site not in spec.sites:
            raise Invalid(f"baseline for an unknown site {cell.site!r}")
        if not 0 < cell.survival < 1:
            raise Invalid(f"baseline survival must be between 0 and 1, not {cell.survival}")
        if cell.excess_share is not None and not 0 < cell.excess_share <= 1:
            raise Invalid(f"an excess share must be in (0, 1], not {cell.excess_share}")
    for p in spec.parameters.values():
        if p.form is not Form.VALUE and p.estimate <= 0:
            raise Invalid(f"{p.name}: a ratio must be positive, not {p.estimate}")
        for bound in (p.ci_low, p.ci_high):
            if bound is not None and p.form is not Form.VALUE and bound <= 0:
                raise Invalid(f"{p.name}: an interval bound must be positive, not {bound}")
    ids = [c.id for c in spec.criteria]
    if len(set(ids)) != len(ids):
        raise Invalid("criteria ids must be unique")
    for criterion in spec.criteria:
        if criterion.site not in spec.sites:
            raise Invalid(f"criterion {criterion.id} names an unknown site {criterion.site!r}")
        if not criterion.countries:
            raise Invalid(f"criterion {criterion.id} names no country")
    for t in spec.targets:
        if t.site not in spec.sites:
            raise Invalid(f"a target names an unknown site {t.site!r}")
        if not t.days_by_country:
            raise Invalid(f"the target for {t.site} {t.step} names no country")
    for key, name in spec.arrows.items():
        if name not in spec.parameters:
            raise Invalid(f"arrow {key!r} names an unknown parameter {name!r}")
    names = {t.name for t in spec.toggles}
    if len(names) != len(spec.toggles):
        raise Invalid("toggle names must be unique")
    # Every combination of toggles is evaluated: 2^n settings per evaluation.
    if len(spec.toggles) > MAX_TOGGLES:
        raise Invalid(f"a model has at most {MAX_TOGGLES} toggles, not {len(spec.toggles)}")
    for key, figure in spec.comparison.survival.items():
        if not 0 < figure < 1:
            raise Invalid(f"comparison survival for {key} must be between 0 and 1, not {figure}")
    for flag in spec.flags:
        if flag.term not in {t.name for t in spec.terms}:
            raise Invalid(f"flag names an unknown term {flag.term!r}")


def _targets(spec: ModelSpec) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for t in spec.targets:
        step = t.step.value if t.step else PATHWAY
        modality = t.modality.value if t.modality else ANY
        days = round(median(t.days_by_country.values()))
        out.setdefault(t.site, {}).setdefault(step, {})[modality] = days
    return out


def _unconverted(spec: ModelSpec) -> list[str]:
    """A warning per site with a baseline cell that has no excess share: its profiles use the
    overall-mortality HRs as they are. The conversion itself is per profile, with the share
    of the profile's own cell (evaluate.to_excess); there is one path, not two."""
    return [
        f"no excess share is loaded for some {site} baselines, so their overall-mortality HRs "
        "are used unconverted"
        for site in spec.sites
        if any(c.excess_share is None for c in spec.baseline if c.site == site)
    ]


def _population(
    spec: ModelSpec, targets: dict[str, dict[str, dict[str, int]]]
) -> tuple[list[PopulationFigure], list[str]]:
    """Per site and sex: the baseline lowered by the comparison country's extra days, as an
    upper bound on what timing explains: the per-4-weeks rate (Hanna) over every extra day
    with a target, before the trigger as well as after it."""
    figures: list[PopulationFigure] = []
    warnings: list[str] = []
    for site in spec.sites:
        typical = spec.comparison.days.get(site, {})
        per_4_weeks = next(
            (
                spec.parameters[name]
                for key, name in spec.arrows.items()
                if key.startswith(f"delay_post:{site}")
                and spec.parameters[name].form is Form.PER_4_WEEKS
            ),
            None,
        )
        stepped = [s for s in STEPS if target(targets, site, s, Modality.SURGERY) is not None]
        extra = sum(typical.get(s, 0) for s in stepped) - sum(
            target(targets, site, s, Modality.SURGERY) or 0 for s in stepped
        )
        for sex in sorted({c.sex for c in spec.baseline if c.site == site}):
            cell = baseline_cell(spec, site, sex, None, None)
            observed = spec.comparison.survival.get(f"{site}:{sex}")
            if cell is None or observed is None:
                warnings.append(f"no comparison survival for {site} ({sex}); its residual is 1")
                continue
            if per_4_weeks is None or extra <= 0:
                log_hr, note = (
                    0.0,
                    "no per-4-weeks delay effect, or no extra days: timing adjusts nothing",
                )
            else:
                hr, warning = to_excess(per_4_weeks, cell)
                if warning:
                    warnings.append(warning)
                log_hr = math.log(hr) * extra / 28
                note = (
                    f"{per_4_weeks.provenance.source}: HR {per_4_weeks.estimate} per 4 weeks over "
                    f"{extra} extra days in {spec.comparison.country}; an upper bound, since the "
                    "rate was estimated for waits after diagnosis"
                )
            adjusted_hazard = -math.log(cell.survival) * math.exp(log_hr)
            residual = -math.log(observed) / adjusted_hazard
            figures.append(
                PopulationFigure(
                    site=site,
                    sex=sex,
                    baseline=per100(cell.survival),
                    timing_adjusted=per100(math.exp(-adjusted_hazard)),
                    observed=per100(observed),
                    residual=residual,
                    note=note,
                )
            )
    return figures, warnings


def _validation(spec: ModelSpec) -> list[ValidationCheck]:
    """Checks against figures the model was not built from: Hanna's own worked examples
    (eight and twelve weeks of delay compound the per-4-weeks HR), and the education gap
    Pokhrel observed in Finland, as the ratio of cumulative excess hazards, basic vs high
    education, against the direct education HR the model carries."""
    checks: list[ValidationCheck] = []
    for key, name in spec.arrows.items():
        parameter = spec.parameters[name]
        if parameter.form is not Form.PER_4_WEEKS:
            continue
        for weeks in (8, 12):
            checks.append(
                ValidationCheck(
                    name=f"{key}: {weeks} weeks of delay",
                    expected=round(parameter.estimate ** (weeks / 4), 4),
                    predicted=round(math.exp(math.log(parameter.estimate) * weeks * 7 / 28), 4),
                    note=(
                        f"{parameter.provenance.source}: the per-4-weeks HR compounded, as "
                        "the paper's own examples do"
                    ),
                )
            )
    by_education = spec.comparison.survival_by_education
    for site in spec.sites:
        for sex in sorted({c.sex for c in spec.baseline if c.site == site}):
            basic = by_education.get(f"{site}:{sex}:basic")
            high = by_education.get(f"{site}:{sex}:tertiary")
            direct = None
            for key in (
                f"direct_education:{site}:{sex}",
                f"direct_education:{site}",
                "direct_education",
            ):
                if key in spec.arrows:
                    direct = spec.parameters[spec.arrows[key]]
                    break
            if basic is None or high is None or direct is None:
                continue
            source = spec.comparison.education_provenance
            checks.append(
                ValidationCheck(
                    name=f"education gap, {site}, {sex}",
                    expected=round(math.log(basic) / math.log(high), 3),
                    predicted=round(direct.estimate, 3),
                    note=(
                        "Ratio of cumulative excess hazards, basic vs high education: "
                        f"observed in {source.source if source else 'the comparison'} "
                        f"({basic:.3f} vs {high:.3f} 5-year cause-specific survival) "
                        f"against the direct HR of {direct.provenance.source}"
                    ),
                )
            )
    return checks


def compile_spec(spec: ModelSpec) -> Compiled:
    validate(spec)
    targets = _targets(spec)
    warnings = _unconverted(spec)
    population, more = _population(spec, targets)
    if not any(c.stage is TriggerStage.WELL_FOUNDED for c in spec.criteria):
        warnings.append("no well-founded-suspicion criteria: the trigger never fires")
    return Compiled(
        targets=targets,
        parameters=dict(spec.parameters),
        population=tuple(population),
        validation=tuple(_validation(spec)),
        warnings=tuple(dict.fromkeys(warnings + more)),
    )
