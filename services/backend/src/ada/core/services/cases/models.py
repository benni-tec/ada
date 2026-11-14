"""What a model kind needs from a case, and how it runs on one. One adapter per kind; a
new kind (a trial matcher, say) is one more entry in KINDS."""

import re
from typing import Protocol

from ada.core.models.base import JsonObject
from ada.core.models.cases import Field, FieldType, Section
from ada.core.models.errors import Invalid
from ada.core.models.statistical_models import (
    Deadline,
    DeadlineStatus,
    EvaluationInputs,
    Intent,
    Modality,
    ModelVersion,
    PathwayStep,
)
from ada.core.services.statistical_models import pathway
from ada.core.services.statistical_models.evaluate import evaluate


class CaseModel(Protocol):
    def requires(self, version: ModelVersion) -> tuple[Field, ...]:
        """The fields this version reads, with the levels it accepts."""
        ...

    def run(self, version: ModelVersion, values: JsonObject) -> Section:
        """The version's result for a case's values (only the fields it requires)."""
        ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


class PathwayModel:
    """The patient pathway model on a case: the fields come from its spec's terms,
    criteria and steps; the section leads with the most pressing deadline."""

    def requires(self, version: ModelVersion) -> tuple[Field, ...]:
        spec = version.spec
        terms = {t.name: t for t in spec.terms}

        def term(name: str, label: str) -> Field:
            return Field(name=name, type=FieldType.ENUM, levels=terms[name].levels, label=label)

        return (
            Field(name="site", type=FieldType.ENUM, levels=spec.sites, required=True, label="Site"),
            term("sex", "Sex").model_copy(update={"required": True}),
            term("age_band", "Age group"),
            term("education", "Education"),
            term("route", "Route to diagnosis"),
            term("stage", "Stage"),
            Field(
                name="intent",
                type=FieldType.ENUM,
                levels=tuple(i.value for i in Intent),
                label="Treatment intent",
            ),
            Field(
                name="modality",
                type=FieldType.ENUM,
                levels=tuple(m.value for m in Modality),
                label="First treatment",
            ),
            Field(
                name="presentation",
                type=FieldType.ENUM_LIST,
                levels=tuple(dict.fromkeys(c.id for c in spec.criteria)),
                label="Presentation",
                help="The pathway criteria the presentation meets",
            ),
            Field(
                name="days",
                type=FieldType.DAY_MAP,
                levels=tuple(s.value for s in PathwayStep),
                label="Days per step",
                help="Days spent in each step so far; a step left out has not started",
            ),
            Field(name="treatment_started", type=FieldType.BOOLEAN, label="Treatment started"),
        )

    def run(self, version: ModelVersion, values: JsonObject) -> Section:
        inputs = EvaluationInputs.model_validate(values)
        result = evaluate(version, inputs)
        summary, status = _headline(result.deadlines, result.trigger.well_founded.fired)
        if not result.trigger.well_founded.fired and result.trigger.suspicion.fired:
            summary, status = "Suspicion met: imaging decides", "info"
        columns: dict[str, str | int | float | bool | None] = {
            "trigger": "well_founded"
            if result.trigger.well_founded.fired
            else "suspicion"
            if result.trigger.suspicion.fired
            else "none",
            "clock_start": result.trigger.clock_start,
            "days_behind": result.days_behind,
            "survival_now": result.survival.now,
            "survival_on_target": result.survival.on_target,
        }
        for d in result.deadlines:
            slug = _slug(d.label)
            columns[f"{slug}_status"] = d.status.value
            columns[f"{slug}_by"] = d.by
        return Section(
            kind=pathway.KIND,
            title="Patient pathway model",
            summary=summary,
            status=status,
            columns=columns,
            body=result.model_dump(mode="json"),
        )


def _headline(deadlines: tuple[Deadline, ...], fired: bool) -> tuple[str, str]:
    """The deadline that matters most: overdue first, then the next one due, then how
    the pathway ended."""
    if not fired:
        return "No pathway criterion met", "info"
    live = [d for d in deadlines if d.status is not DeadlineStatus.NOT_APPLICABLE]
    overdue = [d for d in live if d.status is DeadlineStatus.OVERDUE]
    if overdue:
        worst = max(overdue, key=lambda d: d.by)
        return f"{worst.label} overdue by {_days(worst.by)}", "urgent"
    due = [d for d in live if d.status is DeadlineStatus.DUE]
    if due:
        soonest = min(due, key=lambda d: d.by)
        when = "today" if soonest.by == 0 else f"in {_days(soonest.by)}"
        return f"{soonest.label} due {when}", "warn" if soonest.by <= 3 else "info"
    if live:
        last = live[-1]
        if last.status is DeadlineStatus.LATE:
            return f"{last.label} {_days(last.by)} late", "warn"
        return f"{last.label} on target", "ok"
    return "Pathway started", "info"


KINDS: dict[str, CaseModel] = {pathway.KIND: PathwayModel()}


def adapter(kind: str) -> CaseModel:
    try:
        return KINDS[kind]
    except KeyError:
        raise Invalid(f"Models of kind {kind} cannot run on cases") from None


def pathway_case_type_fields(version: ModelVersion) -> tuple[Field, ...]:
    """The shipped "Suspected cancer pathway" case type: what the pathway model needs,
    site and sex required, plus the county and who referred the patient."""
    needs = PathwayModel().requires(version)
    return needs + (
        Field(name="county", type=FieldType.TEXT, label="Wellbeing services county"),
        Field(name="referred_by", type=FieldType.TEXT, label="Referred by"),
    )
