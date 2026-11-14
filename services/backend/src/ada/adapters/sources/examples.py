"""Registrations of the public sources behind the health demo (spec: Data availability for
the health demo), as data. Seeding a demo project registers each of them:

    for example in EXAMPLES:
        await sources.register(project_id, **example.registration())

All three are open APIs that need no key. Their recorded answers are in
tests/recordings, and tests/test_sources_examples.py refreshes each one through them.
"""

from typing import Any

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.schema import Column, ColumnType, MeasureRole, Roles, Schema
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy

DAY = 24 * 60 * 60


class ExampleSource(DomainModel):
    """The arguments of SourceService.register, except the project."""

    name: str
    access_kind: AccessKind
    address: str
    format: DataFormat
    options: JsonObject = {}
    freshness: FreshnessPolicy = FreshnessPolicy()
    declared_schema: Schema | None = None

    def registration(self) -> dict[str, Any]:
        """Keyword arguments for SourceService.register."""
        return {name: getattr(self, name) for name in type(self).model_fields}


def _columns(**types: ColumnType) -> tuple[Column, ...]:
    return tuple(Column(name=name, type=type) for name, type in types.items())


INTEGER, NUMBER, TEXT = ColumnType.INTEGER, ColumnType.NUMBER, ColumnType.TEXT

# Strategy objective 2: 80% participation in every wellbeing services county. Sotkanet
# answers for every region it knows, from municipalities to the whole country; `region` is
# Sotkanet's own region id. Its indicators carry the date their data was last updated,
# which makes a cheap probe.
SOTKANET_BREAST_SCREENING = ExampleSource(
    name="Breast cancer screening participation (Sotkanet 3621)",
    access_kind=AccessKind.URL,
    address=(
        "https://sotkanet.fi/rest/1.1/json?indicator=3621&years=2023&years=2024&genders=total"
    ),
    format=DataFormat.JSON,
    options={
        "fields": {
            "indicator": {"path": "indicator", "type": "integer"},
            "region": {"path": "region", "type": "integer"},
            "year": {"path": "year", "type": "integer"},
            "gender": {"path": "gender", "type": "text"},
            "value": {"path": "value", "type": "number"},
            "count": {"path": "absValue", "type": "integer"},
        },
        "probe": {
            "url": "https://sotkanet.fi/rest/1.1/indicators/3621",
            "field": "data-updated",
        },
    },
    freshness=FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=DAY),
    declared_schema=Schema(
        columns=_columns(
            indicator=INTEGER,
            region=INTEGER,
            year=INTEGER,
            gender=TEXT,
            value=NUMBER,
            count=INTEGER,
        ),
        roles=Roles(measures=(MeasureRole(value="value"),)),
    ),
)

# Strategy objective 3: cancer mortality. PxWeb takes a JSON query by POST and answers
# with a wide CSV, one column per year and measure; the header is renamed to names SQL can
# use without quoting. Cause codes: 04-21 all malignant neoplasms, 09 liver, 10 pancreas,
# 11 lung, the three poor-prognosis cancers the strategy names.
STATFIN_CANCER_DEATHS = ExampleSource(
    name="Cancer deaths by wellbeing services county (Statistics Finland 13u5)",
    access_kind=AccessKind.REQUEST,
    address="https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/13u5.px",
    format=DataFormat.CSV,
    options={
        "method": "POST",
        "body": {
            "query": [
                {"code": "alue_23_20260101", "selection": {"filter": "all", "values": ["*"]}},
                {
                    "code": "kuolinsyyt_1_20210101",
                    "selection": {"filter": "item", "values": ["04-21", "09", "10", "11"]},
                },
                {
                    "code": "timeperiod_y",
                    "selection": {"filter": "item", "values": ["2022", "2023", "2024"]},
                },
                {
                    "code": "contentscode",
                    "selection": {"filter": "item", "values": ["ksyylkm", "ksyycdr"]},
                },
            ],
            "response": {"format": "csv"},
        },
        "csv": {
            "columns": [
                "county",
                "cause",
                "deaths_2022",
                "death_rate_2022",
                "deaths_2023",
                "death_rate_2023",
                "deaths_2024",
                "death_rate_2024",
            ],
            # PxWeb's marks for a missing and a logically impossible value.
            "null_values": ["..", "."],
        },
    },
    # Published once a year; a weekly look is plenty.
    freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=7 * DAY),
    declared_schema=Schema(
        columns=_columns(
            county=TEXT,
            cause=TEXT,
            deaths_2022=INTEGER,
            death_rate_2022=NUMBER,
            deaths_2023=INTEGER,
            death_rate_2023=NUMBER,
            deaths_2024=INTEGER,
            death_rate_2024=NUMBER,
        )
    ),
)

# Nordic comparison: five-year relative survival of lung cancer (NORDCAN cancer 160) for
# Denmark, Finland, Norway and Sweden, men (sex 1) and women (sex 2), by five-year period.
# The rows are under `dataset`, each with the survival estimate and its interval as
# strings in a nested object.
NORDCAN_LUNG_SURVIVAL = ExampleSource(
    name="Lung cancer five-year survival, Nordic countries (NORDCAN)",
    access_kind=AccessKind.URL,
    address=(
        "https://canapi.iarc.who.int/api/nordcan/v2/961/survival/population/5/1_2/"
        "208_246_578_752/160/?&surv_period=5&age_surv=0&year_start=1967&year_end=2024"
    ),
    format=DataFormat.JSON,
    options={
        "rows": "dataset",
        "fields": {
            "country": {"path": "label", "type": "text"},
            "country_code": {"path": "country", "type": "integer"},
            "sex": {"path": "sex", "type": "integer"},
            "period": {"path": "period", "type": "text"},
            "year": {"path": "year", "type": "integer"},
            "survival": {"path": "survival.value", "type": "number"},
            "survival_lower": {"path": "survival.lowCI", "type": "number"},
            "survival_upper": {"path": "survival.upCI", "type": "number"},
        },
    },
    # NORDCAN is updated about once a year.
    freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=30 * DAY),
    declared_schema=Schema(
        columns=_columns(
            country=TEXT,
            country_code=INTEGER,
            sex=INTEGER,
            period=TEXT,
            year=INTEGER,
            survival=NUMBER,
            survival_lower=NUMBER,
            survival_upper=NUMBER,
        ),
        roles=Roles(
            measures=(
                MeasureRole(value="survival", lower="survival_lower", upper="survival_upper"),
            )
        ),
    ),
)

EXAMPLES = (SOTKANET_BREAST_SCREENING, STATFIN_CANCER_DEATHS, NORDCAN_LUNG_SURVIVAL)
