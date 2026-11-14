"""Daily registry registrations; arrays stay JSON so SQL retains every site."""

from ada.adapters.sources.examples import DAY, ExampleSource
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.sources import AccessKind, DataFormat, FreshnessKind, FreshnessPolicy

COUNTRIES = {"Finland": 246, "Sweden": 752, "Norway": 578, "Denmark": 208}
CTGOV_URL = "https://clinicaltrials.gov/api/v2/studies"
QUERY = (
    "cancer+OR+neoplasm+OR+tumor+OR+carcinoma+OR+lymphoma+OR+leukemia"
    "+OR+myeloma+OR+sarcoma+OR+melanoma+OR+glioma+OR+glioblastoma+OR+mesothelioma"
)
FIELDS = (
    "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionType,InterventionName,LeadSponsorName,"
    "LeadSponsorClass,Sex,MinimumAge,MaximumAge,EligibilityCriteria,"
    "LocationFacility,LocationCity,LocationCountry,LocationStatus,LocationGeoPoint,LastUpdatePostDate,StartDate"
)
CTIS_URL = "https://euclinicaltrials.eu/ctis-public-api/search"
DAILY = FreshnessPolicy(kind=FreshnessKind.PROBE, ttl_seconds=DAY)


def _ctgov(country: str) -> ExampleSource:
    base = (
        f"{CTGOV_URL}?query.cond={QUERY}&query.locn={country}"
        "&filter.overallStatus=RECRUITING&filter.advanced=AREA%5BStudyType%5DINTERVENTIONAL"
    )
    paths = {
        "nct_id": "identificationModule.nctId",
        "title": "identificationModule.briefTitle",
        "overall_status": "statusModule.overallStatus",
        "phases": "designModule.phases",
        "conditions": "conditionsModule.conditions",
        "interventions": "armsInterventionsModule.interventions",
        "sponsor": "sponsorCollaboratorsModule.leadSponsor.name",
        "sponsor_class": "sponsorCollaboratorsModule.leadSponsor.class",
        "sex": "eligibilityModule.sex",
        "min_age": "eligibilityModule.minimumAge",
        "max_age": "eligibilityModule.maximumAge",
        "eligibility": "eligibilityModule.eligibilityCriteria",
        "locations": "contactsLocationsModule.locations",
        "last_update": "statusModule.lastUpdatePostDateStruct.date",
    }
    return ExampleSource(
        name=f"ClinicalTrials.gov: {country}",
        access_kind=AccessKind.URL,
        address=f"{base}&pageSize=1000&fields={FIELDS}",
        format=DataFormat.JSON,
        options={
            "rows": "studies",
            "fields": {
                name: {
                    "path": f"protocolSection.{path}",
                    "type": "json"
                    if name in {"phases", "conditions", "interventions", "locations"}
                    else "text",
                }
                for name, path in paths.items()
            },
            "paginate": {"token": "nextPageToken", "param": "pageToken"},
            "probe": {
                "url": (
                    f"{base}&pageSize=1&countTotal=true&sort=LastUpdatePostDate:desc"
                    "&fields=NCTId,LastUpdatePostDate"
                ),
                "fields": [
                    "totalCount",
                    "studies.0.protocolSection.statusModule.lastUpdatePostDateStruct.date",
                ],
            },
        },
        freshness=DAILY,
    )


def _ctis(country: str, code: int) -> ExampleSource:
    def body(size: int) -> dict:
        return {
            "pagination": {"page": 1, "size": size},
            "sort": {"property": "decisionDate", "direction": "DESC"},
            "searchCriteria": {"msc": [code]},
        }

    paths = {
        "ct_number": "ctNumber",
        "title": "ctTitle",
        "sponsor": "sponsor",
        "sponsor_type": "sponsorType",
        "phase": "trialPhase",
        "conditions": "conditions",
        "trial_countries": "trialCountries",
        "therapeutic_areas": "therapeuticAreas",
        "decision_date": "decisionDateOverall",
    }
    return ExampleSource(
        name=f"CTIS: {country}",
        access_kind=AccessKind.REQUEST,
        address=CTIS_URL,
        format=DataFormat.JSON,
        options={
            "method": "POST",
            "headers": {"Content-Type": "application/json", "Accept": "application/json"},
            "body": body(1000),
            "rows": "data",
            "fields": {
                name: {
                    "path": path,
                    "type": "json" if name in {"trial_countries", "therapeutic_areas"} else "text",
                }
                for name, path in paths.items()
            },
            "paginate": {"more": "pagination.nextPage", "page": "pagination.page"},
            "probe": {
                "url": CTIS_URL,
                "method": "POST",
                "body": body(1),
                "fields": [
                    "pagination.totalRecords",
                    "data.0.ctNumber",
                    "data.0.lastPublicationUpdate",
                ],
            },
        },
        freshness=DAILY,
    )


def _declared(source: ExampleSource) -> ExampleSource:
    """Allow SQL validation at seed time without fetching registry data."""
    return source.model_copy(
        update={
            "declared_schema": Schema(
                columns=tuple(
                    Column(name=name, type=ColumnType(spec["type"]))
                    for name, spec in source.options["fields"].items()
                )
            )
        }
    )


CTGOV = tuple(_declared(_ctgov(country)) for country in COUNTRIES)
CTIS = tuple(_declared(_ctis(country, code)) for country, code in COUNTRIES.items())
SOURCES = CTGOV + CTIS
