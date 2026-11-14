"""Registrations of the public sources behind the health demo (spec: Data availability for
the health demo), as data. Seeding a demo project registers each of them:

    for example in EXAMPLES:
        await sources.register(project_id, **example.registration())

All of them are open APIs that need no key. Their recorded answers are in
tests/recordings, and tests/test_sources_examples.py refreshes each one through them.
"""

from typing import Any

from ada.core.models.base import DomainModel, JsonObject
from ada.core.models.schema import (
    Column,
    ColumnType,
    GeoRole,
    MeasureRole,
    Roles,
    Schema,
    TimeRole,
)
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy
from ada.core.models.time import Grain

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
DATE, JSON = ColumnType.DATE, ColumnType.JSON

# Strategy objective 2: 80% participation in every wellbeing services county. Sotkanet
# answers for every region it knows, from municipalities to the whole country; `region` is
# Sotkanet's own region id, so the level is mixed (SOTKANET_REGIONS maps it). Its
# indicators carry the date their data was last updated, which makes a cheap probe.
#
# The worked example of pushdown: Sotkanet takes the years to answer for as repeated
# `years` parameters, so a run for 2015-2024 asks for exactly those years and stores each
# as a snapshot of its own. The years in the address are what a run without a time range
# reads.
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
        "period": {"column": "year"},
        "pushdown": {"param": "years"},
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
            period_start=DATE,
            period_end=DATE,
        ),
        roles=Roles(
            time=TimeRole(start="period_start", end="period_end", grain=Grain.YEAR),
            geo=GeoRole(code="region", system="sotkanet", level="mixed"),
            measures=(MeasureRole(value="value"),),
        ),
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
# strings in a nested object. A period is a window such as "2020-2024": one interval, so
# the time role has no grain, and NORDCAN cannot be asked for some windows only; a run
# with a time range keeps the windows that overlap it.
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
        "period": {"column": "period"},
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
            period_start=DATE,
            period_end=DATE,
        ),
        roles=Roles(
            time=TimeRole(start="period_start", end="period_end"),
            geo=GeoRole(code="country_code", system="iso3166_numeric", level="country"),
            measures=(
                MeasureRole(value="survival", lower="survival_lower", upper="survival_upper"),
            ),
        ),
    ),
)

# Reference data (spec: Semantic roles). Sotkanet's regions with their level (`category`,
# e.g. HYVINVOINTIALUE for a wellbeing services county, KUNTA for a municipality, MAA for
# the country) and their code in Statistics Finland's classification of that level: the
# mapping from Sotkanet's ids to the county codes the boundaries use. `member_of` lists the
# ids of the regions each one belongs to, as JSON. Licence: CC BY 4.0, THL.
SOTKANET_REGIONS = ExampleSource(
    name="Regions and their codes (Sotkanet)",
    access_kind=AccessKind.URL,
    address="https://sotkanet.fi/rest/1.1/regions",
    format=DataFormat.JSON,
    options={
        "fields": {
            "sotkanet_id": {"path": "id", "type": "integer"},
            "category": {"path": "category", "type": "text"},
            "code": {"path": "code", "type": "text"},
            "name": {"path": "title.en", "type": "text"},
            "name_fi": {"path": "title.fi", "type": "text"},
            "member_of": {"path": "memberOf", "type": "json"},
        },
    },
    # Regions change when municipalities merge, once a year at most.
    freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=30 * DAY),
    declared_schema=Schema(
        columns=_columns(
            sotkanet_id=INTEGER,
            category=TEXT,
            code=TEXT,
            name=TEXT,
            name_fi=TEXT,
            member_of=TEXT,
        ),
        roles=Roles(geo=GeoRole(code="sotkanet_id", system="sotkanet", level="mixed")),
    ),
)

# Reference data: the boundaries of the 23 wellbeing services areas (21 counties, the City
# of Helsinki and Åland), generalised for maps at 1:4,500,000, from Statistics Finland's
# open geodata service (WFS). Coordinates are in ETRS-TM35FIN (EPSG:3067), metres on the
# national projection, so a map draws them as they are. One GeoJSON geometry per county,
# kept as its JSON text; about 100 kB for all of them. Licence: CC BY 4.0, Statistics
# Finland ("Source: Statistics Finland, wellbeing services counties").
WELLBEING_COUNTY_BOUNDARIES = ExampleSource(
    name="Wellbeing services county boundaries (Statistics Finland)",
    access_kind=AccessKind.URL,
    address=(
        "https://geo.stat.fi/geoserver/tilastointialueet/wfs?service=WFS&version=2.0.0"
        "&request=GetFeature&typeName=tilastointialueet:hyvinvointialue4500k"
        "&outputFormat=application/json&srsName=EPSG:3067"
    ),
    format=DataFormat.JSON,
    options={
        "rows": "features",
        "fields": {
            "county_code": {"path": "properties.hyvinvointialue", "type": "text"},
            "name": {"path": "properties.name", "type": "text"},
            "name_fi": {"path": "properties.nimi", "type": "text"},
            "geometry": {"path": "geometry", "type": "json"},
        },
    },
    freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=30 * DAY),
    declared_schema=Schema(
        columns=_columns(county_code=TEXT, name=TEXT, name_fi=TEXT, geometry=TEXT),
        roles=Roles(
            geo=GeoRole(code="county_code", system="statfin", level="wellbeing_services_county")
        ),
    ),
)

# The sources of the health demo's numbers.
DATA = (SOTKANET_BREAST_SCREENING, STATFIN_CANCER_DEATHS, NORDCAN_LUNG_SURVIVAL)
# What maps and region mappings need: registered in the same project, like any source.
REFERENCE = (SOTKANET_REGIONS, WELLBEING_COUNTY_BOUNDARIES)
EXAMPLES = DATA + REFERENCE
