"""The trial matcher as a kind (ada.core.services.statistical_models.kinds): which
recruiting Nordic trials a case could be discussed for, from the trials a version pinned
(Felix's `case_trials` data step, docs/trials.md). Structured fields only: the case's site
against the trial's cancer groups, sex, and the age group against the trial's age limits.
The eligibility text is shown as the registry wrote it, never judged; nothing is scored."""

from typing import Literal

from ada.core.models.analysis import Rows
from ada.core.models.base import JsonObject
from ada.core.models.cases import Attention, DefaultCaseType, Field, FieldType, Section
from ada.core.models.schema import Column, ColumnType
from ada.core.models.statistical_models import (
    ModelVersion,
    PinnedTrial,
    TrialMatcherSpec,
    TrialSite,
)
from ada.core.services.statistical_models.pathway import AGE_BANDS, FEMALE, MALE

KIND = "trial_matcher"
NAME = "Trial matcher"
DESCRIPTION = (
    "Recruiting Nordic cancer trials a case could be discussed for, matched on cancer "
    "group, sex and age; trials with a Finnish site first, then the nearest. Eligibility "
    "is shown, not judged."
)

# The cities the trials data measures distances from (docs/trials.md).
CITIES = ("helsinki", "kuopio", "oulu")
# Each wellbeing services county's nearest of the three, by road sense rather than survey;
# a county not listed is measured from Helsinki.
COUNTY_CITY = {
    "Etelä-Savo": "kuopio",
    "Pohjois-Savo": "kuopio",
    "Pohjois-Karjala": "kuopio",
    "Keski-Suomi": "kuopio",
    "Pohjois-Pohjanmaa": "oulu",
    "Kainuu": "oulu",
    "Lappi": "oulu",
    "Keski-Pohjanmaa": "oulu",
    "Pohjanmaa": "oulu",
    "Etelä-Pohjanmaa": "oulu",
}
# The most matches a result keeps; the count says how many there were.
MAX_MATCHES = 25

Fit = Literal["fits", "partly", "unknown"]


def _list(text: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(text or "").split(",") if part.strip())


def _number(value: object) -> float | None:
    return None if value is None else float(str(value))


def pinned(rows: Rows) -> list[PinnedTrial]:
    """The trials as the matcher reads them: one row per trial with, per city, the nearest
    recruiting Nordic site (`<city>_facility`, `_city`, `_country`, `_km`)."""
    names = [c.name for c in rows.columns]
    trials = []
    for values in rows.rows:
        row = dict(zip(names, values, strict=True))
        nearest = {
            city: TrialSite(
                facility=row.get(f"{city}_facility"),
                city=row.get(f"{city}_city"),
                country=str(row.get(f"{city}_country") or ""),
                km=_number(row.get(f"{city}_km")),
            )
            for city in CITIES
            if row.get(f"{city}_country")
        }
        trials.append(
            PinnedTrial(
                nct_id=str(row["nct_id"]),
                title=str(row.get("title") or ""),
                phase=row.get("phase") or None,
                conditions=str(row.get("conditions") or ""),
                cancer_groups=_list(row.get("cancer_groups")),
                sex=str(row.get("sex") or "ALL").upper(),
                min_age_years=_number(row.get("min_age_years")),
                max_age_years=_number(row.get("max_age_years")),
                eligibility=str(row.get("eligibility") or ""),
                recruiting_countries=_list(row.get("recruiting_countries")),
                finnish_site=bool(row.get("finnish_site")),
                nearest=nearest,
                url=str(row.get("url") or f"https://clinicaltrials.gov/study/{row['nct_id']}"),
            )
        )
    return trials


def city_of(county: object) -> str:
    return COUNTY_CITY.get(county, "helsinki") if isinstance(county, str) else "helsinki"


def _band(age_band: object) -> tuple[int, int] | None:
    if not isinstance(age_band, str) or "-" not in age_band:
        return None
    low, high = age_band.split("-", 1)
    return int(low), int(high)


def age_fit(trial: PinnedTrial, age_band: object) -> Fit | None:
    """Whether an age group fits a trial's limits: wholly ("fits"), in part ("partly":
    some ages of the group are outside), unknown without a group; None when no age of
    the group is inside."""
    band = _band(age_band)
    if band is None:
        return "unknown"
    low, high = band
    lowest = trial.min_age_years if trial.min_age_years is not None else 0
    highest = trial.max_age_years if trial.max_age_years is not None else 200
    if high < lowest or low > highest:
        return None
    return "fits" if low >= lowest and high <= highest else "partly"


def matches(spec: TrialMatcherSpec, trials: tuple[PinnedTrial, ...], values: JsonObject):
    """The trials a case's values match, with each one's age fit, in the matcher's order:
    a Finnish site first, then the nearest site from the case's county's city."""
    group = spec.groups.get(str(values.get("site")))
    sex = str(values.get("sex", "")).upper()
    city = city_of(values.get("county"))
    found = []
    for trial in trials:
        if group is None or group not in trial.cancer_groups:
            continue
        if trial.sex not in ("ALL", "") and trial.sex != sex:
            continue
        fit = age_fit(trial, values.get("age_band"))
        if fit is None:
            continue
        found.append((trial, fit))
    near = lambda pair: pair[0].nearest.get(city).km if pair[0].nearest.get(city) else None  # noqa: E731
    found.sort(key=lambda pair: (not pair[0].finnish_site, near(pair) is None, near(pair) or 0))
    return found, city


class TrialKind:
    """The trial matcher on a case. It never asks for attention: a list of trials is
    something to discuss, not a deadline."""

    def requires(self, version: ModelVersion) -> tuple[Field, ...]:
        spec = version.spec
        assert isinstance(spec, TrialMatcherSpec)
        return (
            Field(
                name="site",
                type=FieldType.ENUM,
                levels=tuple(spec.groups),
                required=True,
                label="Site",
            ),
            Field(
                name="sex", type=FieldType.ENUM, levels=(FEMALE, MALE), required=True, label="Sex"
            ),
            Field(name="age_band", type=FieldType.ENUM, levels=AGE_BANDS, label="Age group"),
            Field(name="county", type=FieldType.TEXT, label="Wellbeing services county"),
        )

    def run(self, version: ModelVersion, values: JsonObject) -> Section:
        spec, compiled = version.spec, version.compiled
        assert isinstance(spec, TrialMatcherSpec)
        trials = getattr(compiled, "trials", ())
        found, city = matches(spec, trials, values)
        finnish = sum(1 for trial, _ in found if trial.finnish_site)
        partly = sum(1 for _, fit in found if fit == "partly")
        nearest = [
            trial.nearest[city].km
            for trial, _ in found
            if city in trial.nearest and trial.nearest[city].km is not None
        ]
        if not found:
            summary = "No recruiting trial matches"
        else:
            s = "" if len(found) == 1 else "s"
            summary = f"{len(found)} recruiting trial{s}, {finnish} with a Finnish site"
        body: JsonObject = {
            "city": city,
            "total": len(found),
            "matches": [
                {
                    "nct_id": trial.nct_id,
                    "title": trial.title,
                    "phase": trial.phase,
                    "countries": list(trial.recruiting_countries),
                    "finnish_site": trial.finnish_site,
                    "nearest": trial.nearest[city].model_dump() if city in trial.nearest else None,
                    "age": fit,
                    "min_age_years": trial.min_age_years,
                    "max_age_years": trial.max_age_years,
                    "eligibility": trial.eligibility,
                    "url": trial.url,
                }
                for trial, fit in found[:MAX_MATCHES]
            ],
            "read_at": getattr(compiled, "read_at", None) and compiled.read_at.isoformat(),
        }
        return Section(
            kind=KIND,
            title=NAME,
            summary=summary,
            status="info" if found else "ok",
            columns={
                "trials": len(found),
                "with_finnish_site": finnish,
                "age_uncertain": partly,
                "nearest_km": round(min(nearest)) if nearest else None,
            },
            attention=Attention(open=False),
            body=body,
        )

    def columns(self, version: ModelVersion) -> tuple[Column, ...]:
        return (
            Column(name="trials", type=ColumnType.INTEGER),
            Column(name="with_finnish_site", type=ColumnType.INTEGER),
            Column(name="age_uncertain", type=ColumnType.INTEGER),
            Column(name="nearest_km", type=ColumnType.INTEGER),
        )

    def default_case_type(self, version: ModelVersion) -> DefaultCaseType:
        return DefaultCaseType(
            name="Cancer trial candidate",
            description="A synthetic case to look for recruiting trials for.",
            fields=self.requires(version),
        )
