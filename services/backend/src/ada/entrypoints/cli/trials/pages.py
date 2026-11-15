"""Hospital Markdown lists and bounded sponsor study-page registrations."""

import re
from collections.abc import Sequence
from typing import Any, Literal

from ada.adapters.sources.examples import DAY, ExampleSource
from ada.core.models.schema import Column, ColumnType, Schema
from ada.core.models.sources import (
    AccessKind,
    DataFormat,
    DataSource,
    FreshnessKind,
    FreshnessPolicy,
)

MAX_STUDY_PAGES = 200
WEB_REFRESHES_PER_MINUTE = 8
STUDY_PREFIX = "Sponsor study: "

# Checked against trial_pages.csv on 2026-11-15; the English Pirha duplicate is omitted.
PAGE_DETAILS = (
    (
        "Cancerstudier i Sverige (RCC national database, list)",
        "RCC",
        "Sweden",
        "https://kunskapsbanken.cancercentrum.se/cancerstudier-i-sverige/",
    ),
    (
        "FICAN East (KYS / Itäinen syöpäkeskus) recruiting drug trials",
        "KYS",
        "Finland",
        "https://fican.fi/itainen-syopakeskus/tutkimus-ja-yhteistyo/rekrytoivat-laaketutkimukset/",
    ),
    (
        "FICAN West (Tyks / Läntinen syöpäkeskus) recruiting drug trials",
        "Tyks",
        "Finland",
        "https://fican.fi/lantinen-syopakeskus/tutkimus/rekrytoivat-laaketutkimukset/",
    ),
    (
        "Tays: recruiting cancer trials",
        "Tays",
        "Finland",
        "https://www.pirha.fi/fi/palvelut/sairaalat-tays/syopa/syopatutkimukset",
    ),
    (
        "HUS: recruiting cancer trials",
        "HUS",
        "Finland",
        "https://www.hus.fi/tutkimus-ja-opetus/tieteelliset-tutkimukset/syopatutkimukset",
    ),
    (
        "Nordic SBRT study group trials (Karolinska Institutet)",
        "Karolinska",
        "Sweden",
        "https://ki.se/onkpat/forskning/nordiska-sbrt-studiegruppen/studier-inom-nordiska-sbrt-studiegruppen",
    ),
    (
        "Karolinska CKC kpeks list: ME Övre buk (upper GI)",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/buk_o.php",
    ),
    (
        "Karolinska CKC kpeks list: ME Bäckencancer (pelvic)",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/backen_o.php",
    ),
    (
        "Karolinska CKC kpeks list: ME Huvud-hals-lunga-hud (HHLH)",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/hhlh_o.php",
    ),
    (
        "Karolinska CKC kpeks list: ME Hematologi",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/hemat_o.php",
    ),
    (
        "Karolinska CKC kpeks list: ME Bröst/endokrina/sarkom",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/brost_o.php",
    ),
    (
        "Karolinska CKC kpeks list: Fas 1-enheten",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/fas1enhet_o.php",
    ),
    (
        "Karolinska CKC kpeks list: ME Cellterapi/allo-HSCT",
        "Karolinska",
        "Sweden",
        "http://www.kpeks.se/studier/cellter_o.php",
    ),
    (
        "OUS-research Flatmark group interventional trials",
        "OUS",
        "Norway",
        "https://www.ous-research.no/home/flatmark/Clinical-trials/23885",
    ),
)
Interval = Literal["10min", "hourly", "daily"]
PageKind = Literal["hospital_list", "sponsor_study_page"]


class TrialPage(ExampleSource):
    interval: Interval = "daily"

    def registration(self) -> dict[str, Any]:
        arguments = super().registration()
        arguments.pop("interval")
        return arguments


def hospital_page(
    url: str,
    name: str,
    country: str,
    *,
    hospital: str | None = None,
    interval: Interval | None = None,
) -> TrialPage:
    interval = interval or ("hourly" if country == "Finland" else "daily")
    return TrialPage(
        name=name,
        access_kind=AccessKind.WEB,
        address=url,
        format=DataFormat.HTML,
        interval=interval,
        options={
            "operation": "scrape",
            "extract": "pages",
            "trial_page": {
                "kind": "hospital_list",
                "country": country,
                "hospital": hospital or name,
                "interval": interval,
            },
        },
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=DAY),
    )


PAGES = tuple(
    hospital_page(
        url,
        name,
        country,
        hospital=hospital,
        interval="10min"
        if hospital in {"HUS", "KYS", "Tays"}
        else "hourly"
        if country == "Finland"
        else "daily",
    )
    for name, hospital, country, url in PAGE_DETAILS
)


def page_options(source: ExampleSource | DataSource) -> dict[str, Any]:
    metadata = source.options.get("trial_page")
    if isinstance(metadata, dict):
        return metadata
    # Sources registered by the earlier seed did not yet carry this metadata.
    seeded = next((p for p in PAGES if p.name == source.name), None)
    if seeded is not None:
        return page_options(seeded)
    return (
        {"kind": "sponsor_study_page", "interval": "daily"}
        if source.name.startswith(STUDY_PREFIX)
        else {}
    )


def hospital_trials_sql(sources: Sequence[ExampleSource | DataSource] = PAGES) -> str:
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    pages = " UNION ALL ".join(
        f"SELECT {literal(name)} AS page_name, {literal(hospital)} AS hospital, "
        f"{literal(country)} AS country, string_agg(text, chr(10) ORDER BY page) AS text "
        f"FROM input_{i}"
        for i, source in enumerate(sources)
        for name, hospital, country in [
            (source.name, page_options(source)["hospital"], page_options(source)["country"])
        ]
    )
    return (
        r"""
WITH pages AS ("""
        + pages
        + r"""), lines AS (
    SELECT page_name, hospital, country, line, ordinal,
        CASE WHEN regexp_matches(line, '^\s*#{1,6}\s+')
            THEN regexp_replace(line, '^\s*#{1,6}\s+', '') END AS heading
    FROM pages, unnest(string_split(text, chr(10))) WITH ORDINALITY AS l(line, ordinal)
), sections AS (
    SELECT *, last_value(heading IGNORE NULLS) OVER (
        PARTITION BY page_name ORDER BY ordinal ROWS UNBOUNDED PRECEDING) AS section
    FROM lines
), ids AS (
    SELECT page_name, hospital, country, section, left(trim(line), 400) AS snippet, ordinal,
        unnest(regexp_extract_all(line,
            '\bNCT\d{8}\b|\b20\d{2}-5\d{5}-\d{2}-\d{2}\b|\b\d{4}-\d{6}-\d{2}\b')) AS trial_id
    FROM sections
)
SELECT page_name, hospital, country, trial_id,
    CASE WHEN starts_with(trial_id, 'NCT') THEN 'NCT'
         WHEN length(trial_id) = 17 THEN 'EU CT' ELSE 'EudraCT' END AS id_kind,
    section, snippet
FROM ids
QUALIFY row_number() OVER (PARTITION BY page_name, trial_id ORDER BY ordinal) = 1
ORDER BY country != 'Finland', page_name, trial_id
"""
    )


HOSPITAL_TRIAL_GAPS = """
WITH listed AS (SELECT * FROM input_0 WHERE country = 'Finland')
SELECT 'hospital_only' AS gap_kind, h.trial_id AS nct_id, t.title,
    h.page_name, h.hospital AS facility, NULL::VARCHAR AS city, h.country,
    h.section, h.snippet
FROM listed h LEFT JOIN input_1 t ON h.trial_id = t.nct_id
WHERE h.id_kind = 'NCT' AND NOT coalesce(t.fi_recruiting, false)
UNION ALL
SELECT DISTINCT 'registry_only', t.nct_id, t.title, NULL, s.facility, s.city, s.country,
    NULL, NULL
FROM input_1 t JOIN input_2 s USING (nct_id)
WHERE t.fi_recruiting AND s.country = 'Finland' AND s.site_status = 'RECRUITING'
    AND NOT EXISTS (SELECT 1 FROM listed h WHERE h.trial_id = t.nct_id)
"""

SITE_COLUMNS = ("nct_id", "overall_status", "facility", "city", "country", "site_status")
EMPTY_SITES = "SELECT " + ", ".join(f"NULL::VARCHAR AS {c}" for c in SITE_COLUMNS) + " WHERE false"


def study_page(nct_id: str, sponsor: str) -> TrialPage | None:
    """Only known sponsor URL patterns, with registry IDs validated before interpolation."""
    if not re.fullmatch(r"NCT\d{8}", nct_id):
        return None
    sponsor = sponsor.lower()
    if "astrazeneca" in sponsor:
        url = f"https://www.astrazenecaclinicaltrials.com/study/{nct_id}/"
    elif re.search(r"\bmsd\b|merck sharp.*dohme", sponsor):
        url = f"https://www.merckclinicaltrials.com/trial/{nct_id.lower()}/"
    elif "pfizer" in sponsor:
        url = f"https://www.pfizerclinicaltrials.com/find-a-trial/{nct_id.lower()}"
    else:
        return None
    return sponsor_page(url, STUDY_PREFIX + nct_id)


def sponsor_page(url: str, name: str) -> TrialPage:
    return TrialPage(
        name=name,
        access_kind=AccessKind.WEB,
        address=url,
        format=DataFormat.HTML,
        interval="daily",
        options={
            "trial_page": {"kind": "sponsor_study_page", "interval": "daily"},
            "operation": "extract",
            "instruction": "List only sites in Finland, Sweden, Norway or Denmark. "
            "Copy nct_id, overall_status, facility, city, country and site_status exactly "
            "as this page states them; null where not stated. Do not infer recruitment "
            "from the registry or invent sites.",
        },
        declared_schema=Schema(
            columns=tuple(Column(name=c, type=ColumnType.TEXT) for c in SITE_COLUMNS)
        ),
        freshness=FreshnessPolicy(kind=FreshnessKind.TTL, ttl_seconds=7 * DAY),
    )


def hospital_trial_changes_sql(source: DataSource) -> str:
    """Compare identifiers, so a changed footer or description creates no trial event."""
    sql = hospital_trials_sql([source])
    newest = sql.replace("input_0", "(SELECT * FROM history WHERE snapshot_rank = 1)")
    previous = sql.replace("input_0", "(SELECT * FROM history WHERE snapshot_rank = 2)")
    return f"""
WITH history AS (SELECT * FROM input_0), newest AS ({newest}), previous AS ({previous}),
events AS (
    SELECT 'listed_by_hospital' AS change_kind, n.*
    FROM newest n ANTI JOIN previous p USING (trial_id)
    UNION ALL
    SELECT 'unlisted_by_hospital', p.*
    FROM previous p ANTI JOIN newest n USING (trial_id)
)
SELECT change_kind, page_name AS page, trial_id, hospital, country, id_kind, section, snippet,
    (SELECT max(snapshot_at) FROM history WHERE snapshot_rank = 1) AS snapshot_at
FROM events
WHERE EXISTS (SELECT 1 FROM history WHERE snapshot_rank = 2)
"""
