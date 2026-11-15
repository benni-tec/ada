"""The trial matcher as a kind (ada.core.services.statistical_models.kinds): the recruiting
Nordic trials of a case's cancer group, read from Felix's `case_trials` step (docs/trials.md)
whenever it runs, nearest first. It filters on the cancer group only, a topic match: sex and
age limits are shown beside each trial and never leave one out, and the eligibility text is
shown as the registry wrote it, never judged. Distances are from the city the `county_cities`
step names for the case's county (Helsinki, Kuopio or Oulu)."""

from typing import Literal

from ada.core.models.analysis import Rows
from ada.core.models.base import JsonObject
from ada.core.models.cases import Attention, DefaultCaseType, Field, FieldType, Section
from ada.core.models.schema import Column, ColumnType
from ada.core.models.statistical_models import ModelVersion, TrialMatcherSpec
from ada.core.services.ports.exploration import Clauses
from ada.core.services.statistical_models.pathway import AGE_BANDS, FEMALE, MALE

KIND = "trial_matcher"
NAME = "Trial matcher"
DESCRIPTION = (
    "Recruiting Nordic cancer trials of a case's cancer group, nearest first. Sex and age "
    "limits are shown, not applied; eligibility is shown, not judged."
)

# The cities the trials data measures distances from (docs/trials.md).
CITIES = ("helsinki", "kuopio", "oulu")
DEFAULT_CITY = "helsinki"
# The most trials a result keeps; the count says how many there were.
MAX_MATCHES = 25

Age = Literal["inside", "partly", "outside", "unknown"]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _rows(rows: Rows | None) -> list[dict[str, object]]:
    if rows is None:
        return []
    names = [c.name for c in rows.columns]
    return [dict(zip(names, values, strict=True)) for values in rows.rows]


def _number(value: object) -> float | None:
    return None if value is None else float(str(value))


def _site(value: object) -> JsonObject:
    """The nearest site's record; the fields missing when the trial has no site with a
    distance from the city."""
    site = value if isinstance(value, dict) else {}
    return {
        "facility": site.get("facility"),
        "city": site.get("city"),
        "country": site.get("country"),
        "km": _number(site.get("km")),
    }


def _band(age_band: object) -> tuple[int, int] | None:
    if not isinstance(age_band, str) or "-" not in age_band:
        return None
    low, high = age_band.split("-", 1)
    return int(low), int(high)


def age_fit(min_age: float | None, max_age: float | None, age_band: object) -> Age:
    """How an age group sits against a trial's limits, as information only: inside,
    partly inside, outside, or unknown without a group."""
    band = _band(age_band)
    if band is None:
        return "unknown"
    low, high = band
    lowest = min_age if min_age is not None else 0
    highest = max_age if max_age is not None else 200
    if high < lowest or low > highest:
        return "outside"
    return "inside" if low >= lowest and high <= highest else "partly"


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
            Field(name="sex", type=FieldType.ENUM, levels=(FEMALE, MALE), label="Sex"),
            Field(name="age_band", type=FieldType.ENUM, levels=AGE_BANDS, label="Age group"),
            Field(name="county", type=FieldType.TEXT, label="Wellbeing services county"),
        )

    def queries(self, version: ModelVersion, values: JsonObject) -> dict[str, tuple[str, Clauses]]:
        """The case's cancer group's trials, one row each with its nearest recruiting site
        from each city; and the case county's city, when the matcher has the step for it."""
        spec = version.spec
        assert isinstance(spec, TrialMatcherSpec)
        group = spec.groups.get(str(values.get("site")), "")
        # One record per city, so a site's facility, city and distance come from the same
        # row: arg_min of each field alone skips the rows where that field is NULL.
        nearest = ", ".join(
            f"arg_min({{'facility': facility, 'city': city, 'country': country, "
            f"'km': km_{c}::DOUBLE}}, km_{c}) AS {c}_site"
            for c in CITIES
        )
        found: dict[str, tuple[str, Clauses]] = {
            "trials": (
                spec.operator_id,
                Clauses(
                    select="nct_id, any_value(title) AS title, any_value(phase) AS phase, "
                    "any_value(sex) AS sex, any_value(min_age_years) AS min_age_years, "
                    "any_value(max_age_years) AS max_age_years, "
                    "any_value(eligibility) AS eligibility, "
                    "any_value(recruiting_countries) AS recruiting_countries, "
                    f"bool_or(country = 'Finland') AS finnish_site, {nearest}, "
                    "any_value(url) AS url",
                    where=f"list_contains(string_split(cancer_groups, ', '), {_quote(group)})",
                    group_by="nct_id",
                    order_by="nct_id",
                ),
            )
        }
        county = values.get("county")
        if spec.county_operator_id and isinstance(county, str) and county:
            found["county"] = (
                spec.county_operator_id,
                Clauses(select="city", where=f"county = {_quote(county)}"),
            )
        return found

    def run(self, version: ModelVersion, values: JsonObject, data: dict[str, Rows]) -> Section:
        county = _rows(data.get("county"))
        named = str(county[0].get("city")) if county else ""
        city = named if named in CITIES else DEFAULT_CITY
        trials = []
        for row in _rows(data.get("trials")):
            low, high = _number(row.get("min_age_years")), _number(row.get("max_age_years"))
            countries = str(row.get("recruiting_countries") or "")
            trials.append(
                {
                    "nct_id": row["nct_id"],
                    "title": row.get("title") or "",
                    "phase": row.get("phase"),
                    "countries": [c.strip() for c in countries.split(",") if c.strip()],
                    "finnish_site": bool(row.get("finnish_site")),
                    "nearest": _site(row.get(f"{city}_site")),
                    # Kept missing when the registry gives none: "all sexes" would be a claim.
                    "sex": str(row["sex"]).upper() if row.get("sex") else None,
                    "min_age_years": low,
                    "max_age_years": high,
                    "age": age_fit(low, high, values.get("age_band")),
                    "eligibility": row.get("eligibility") or "",
                    "url": row.get("url") or f"https://clinicaltrials.gov/study/{row['nct_id']}",
                }
            )

        def km(trial: dict) -> float | None:
            return trial["nearest"]["km"]

        trials.sort(key=lambda t: (km(t) is None, km(t) or 0))
        nearest = next((km(t) for t in trials if km(t) is not None), None)
        if not trials:
            summary = "No recruiting trial in this cancer group"
        else:
            s = "" if len(trials) == 1 else "s"
            near = (
                f", nearest {round(nearest)} km from {city.title()}" if nearest is not None else ""
            )
            summary = f"{len(trials)} recruiting trial{s}{near}"
        return Section(
            kind=KIND,
            title=NAME,
            summary=summary,
            status="info" if trials else "ok",
            columns={
                "trials": len(trials),
                "with_finnish_site": sum(1 for t in trials if t["finnish_site"]),
                "nearest_km": None if nearest is None else round(nearest),
                "city": city,
            },
            attention=Attention(open=False),
            body={"city": city, "total": len(trials), "matches": trials[:MAX_MATCHES]},
        )

    def columns(self, version: ModelVersion) -> tuple[Column, ...]:
        return (
            Column(name="trials", type=ColumnType.INTEGER),
            Column(name="with_finnish_site", type=ColumnType.INTEGER),
            Column(name="nearest_km", type=ColumnType.INTEGER),
            Column(name="city", type=ColumnType.TEXT),
        )

    def default_case_type(self, version: ModelVersion) -> DefaultCaseType:
        return DefaultCaseType(
            name="Cancer trial candidate",
            description="A synthetic case to look for recruiting trials for.",
            fields=self.requires(version),
        )
