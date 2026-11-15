"""SQL contracts over registry sources; input order is declared in seed.py."""

_UNION = " UNION ALL ".join(f"SELECT * FROM input_{i}" for i in range(4))
_NORDIC = "('Finland', 'Sweden', 'Norway', 'Denmark')"

CANCER_REGEX = (
    "cancer|neoplas|tumou?r|carcinoma|lymphoma|leuka?emia|myeloma|sarcoma|melanoma|"
    "glioma|blastoma|mesothelioma|malignan|metasta|oncolog"
)

CANCER_PATTERNS = {
    "lung": "lung|nsclc|sclc|bronch",
    "pancreas": "pancrea",
    "liver": "hepatocellular|\\bliver\\b|\\bhcc\\b|hepatic|cholangio|biliary",
    "breast": "breast",
    "colorectal": "colorectal|colon|rectal",
    "prostate": "prostate",
    "blood": "leukemia|leukaemia|lymphoma|myeloma|myelodysplas",
    "skin": "melanoma|skin|cutaneous",
    "brain": "glioma|glioblastoma|brain|central nervous",
}

_GROUPS = ", ".join(
    f"CASE WHEN regexp_matches(lower(conditions), '{pattern}') THEN '{name}' END"
    for name, pattern in CANCER_PATTERNS.items()
)

TRIAL_SITES = f"""
WITH raw AS ({_UNION}), dedup AS (
    SELECT * FROM raw QUALIFY row_number() OVER (PARTITION BY nct_id ORDER BY last_update DESC
    NULLS LAST, locations::VARCHAR DESC) = 1
)
SELECT nct_id, site->>'facility' AS facility, site->>'city' AS city,
    site->>'country' AS country, site->>'status' AS site_status,
    try_cast(site->'geoPoint'->>'lat' AS DOUBLE) AS lat,
    try_cast(site->'geoPoint'->>'lon' AS DOUBLE) AS lon,
    coalesce(site->>'country' IN {_NORDIC}, false) AS is_nordic
FROM dedup, unnest(from_json(locations, '["JSON"]')) AS s(site)
"""
"""Every site, including closed and non-Nordic sites, of each deduplicated trial."""


def _age(column: str) -> str:
    return f"""try_cast(regexp_extract({column}, '(\\d+(?:\\.\\d+)?)', 1) AS DOUBLE)
        / CASE WHEN {column} ILIKE '%month%' THEN 12
               WHEN {column} ILIKE '%week%' THEN 52.1775
               WHEN {column} ILIKE '%day%' THEN 365.25 ELSE 1 END"""


TRIALS = f"""
WITH raw AS ({_UNION}), dedup AS (
    SELECT * FROM raw QUALIFY row_number() OVER (PARTITION BY nct_id ORDER BY last_update DESC
    NULLS LAST, locations::VARCHAR DESC) = 1
), parsed AS (
    SELECT * EXCLUDE(conditions),
        array_to_string(from_json(conditions, '["VARCHAR"]'), '; ') AS conditions
    FROM dedup
), grouped AS (
    SELECT *, concat_ws(', ', {_GROUPS}) AS groups FROM parsed
)
SELECT nct_id, title, overall_status,
    array_to_string(from_json(phases, '["VARCHAR"]'), '/') AS phase, conditions,
    CASE WHEN groups = '' THEN 'other' ELSE groups END AS cancer_groups,
    array_to_string(list_sort(list_distinct(list_transform(
        from_json(interventions, '["JSON"]'), lambda x: x->>'type'))), '; ') AS intervention_types,
    coalesce(list_contains(list_transform(from_json(interventions, '["JSON"]'), lambda x:
    x->>'type'), 'DRUG')
        OR list_contains(list_transform(from_json(interventions, '["JSON"]'), lambda x:
    x->>'type'), 'BIOLOGICAL'), false) AS is_drug,
    sponsor, sponsor_class, sex, {_age("min_age")} AS min_age_years,
    {_age("max_age")} AS max_age_years, eligibility,
    (SELECT string_agg(DISTINCT site->>'country', ', ' ORDER BY site->>'country')
        FROM unnest(from_json(locations, '["JSON"]')) AS s(site)
        WHERE site->>'country' IN {_NORDIC} AND site->>'status' = 'RECRUITING') AS
    recruiting_countries,
    coalesce(list_contains(list_transform(from_json(locations, '["JSON"]'), lambda x:
    x->>'country'), 'Finland'), false) AS has_fi_site,
    coalesce(list_contains(list_transform(from_json(locations, '["JSON"]'), lambda x:
    (x->>'country' = 'Finland' AND x->>'status' = 'RECRUITING')), true), false) AS fi_recruiting,
    try_cast(last_update AS DATE) AS last_update,
    'https://clinicaltrials.gov/study/' || nct_id AS url
FROM grouped
WHERE regexp_matches(lower(conditions), '{CANCER_REGEX}')
"""
"""One CT.gov trial with eligibility preserved and cancer groups derived from conditions."""


def _km(lat: float, lon: float) -> str:
    return f"""CASE WHEN lat IS NULL OR lon IS NULL THEN NULL
        ELSE 6371 * 2 * asin(sqrt(least(1.0,
        pow(sin(radians(lat - {lat}) / 2), 2)
        + cos(radians({lat})) * cos(radians(lat))
        * pow(sin(radians(lon - {lon}) / 2), 2)))) END"""


_DISTANCES = f"""{_km(60.1699, 24.9384)} AS km_helsinki,
    {_km(62.8924, 27.6770)} AS km_kuopio, {_km(65.0121, 25.4651)} AS km_oulu"""

TRIAL_DOORS = f"""
WITH sites AS (
    SELECT *, {_DISTANCES} FROM input_1
    WHERE country IN ('Sweden', 'Norway', 'Denmark') AND site_status = 'RECRUITING'
), nearest AS (
    SELECT *, min(km_kuopio) OVER w AS kuopio, min(km_oulu) OVER w AS oulu,
        string_agg(DISTINCT country, ', ' ORDER BY country) OVER w AS open_countries
    FROM sites WINDOW w AS (PARTITION BY nct_id)
    QUALIFY row_number() OVER (PARTITION BY nct_id ORDER BY km_helsinki NULLS LAST, country,
    city, facility) = 1
)
SELECT t.nct_id, title, phase, cancer_groups, is_drug, sponsor, sponsor_class,
    open_countries, facility AS nearest_facility, city AS nearest_city,
    country AS nearest_country, km_helsinki, kuopio AS km_kuopio, oulu AS km_oulu, url
FROM input_0 t JOIN nearest USING (nct_id)
WHERE NOT has_fi_site AND overall_status = 'RECRUITING'
"""
"""Open neighbouring-country trials with no Finnish site; distances use each city's nearest site."""

_LABEL = """CASE {code}
    WHEN '2' THEN 'authorised, recruitment pending'
    WHEN '3' THEN 'ongoing, recruitment pending'
    WHEN '4' THEN 'ongoing, recruiting'
    WHEN '5' THEN 'ongoing, recruitment ended'
    WHEN '6' THEN 'halted' WHEN '7' THEN 'suspended' WHEN '8' THEN 'ended'
    WHEN '11' THEN 'not authorised' ELSE 'unknown (' || {code} || ')' END"""
_STATUSES = ", ".join(
    f"""(SELECT {_LABEL.format(code="split_part(c, ':', 2)")}
        FROM unnest(from_json(trial_countries, '["VARCHAR"]')) a(c)
        WHERE split_part(c, ':', 1) = '{country}' LIMIT 1) AS status_{code}"""
    for country, code in (("Finland", "fi"), ("Sweden", "se"), ("Norway", "no"), ("Denmark", "dk"))
)
CTIS_TRIALS = f"""
WITH raw AS ({_UNION}), dedup AS (
    SELECT * FROM raw QUALIFY row_number() OVER (PARTITION BY ct_number ORDER BY
    try_strptime(decision_date, '%d/%m/%Y') DESC NULLS LAST, trial_countries::VARCHAR DESC) = 1
)
SELECT ct_number, title, sponsor, sponsor_type, phase, conditions,
    coalesce(contains(therapeutic_areas::VARCHAR, 'C04'), false) AS is_oncology,
    {_STATUSES}, try_strptime(decision_date, '%d/%m/%Y')::DATE AS decision_date,
    'https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT=' || ct_number AS url
FROM dedup
"""
"""Deduplicated CTIS trials. Country status labels are [inferred] from registry samples."""

CTIS_FINLAND_PENDING = """
SELECT ct_number, title, sponsor, sponsor_type, phase, status_fi,
    concat_ws(', ', CASE WHEN status_se = 'ongoing, recruiting' THEN 'Sweden' END,
        CASE WHEN status_no = 'ongoing, recruiting' THEN 'Norway' END,
        CASE WHEN status_dk = 'ongoing, recruiting' THEN 'Denmark' END) AS recruiting_in,
    decision_date, url
FROM input_0 WHERE is_oncology AND status_fi IN
    ('authorised, recruitment pending', 'ongoing, recruitment pending')
"""
"""Oncology trials listing Finland with inferred pending codes 2 or 3."""

CASE_TRIALS = f"""
SELECT t.nct_id, title, phase, overall_status, conditions, cancer_groups, sex,
    min_age_years, max_age_years, eligibility, recruiting_countries,
    facility, city, country, lat, lon, {_DISTANCES}, url
FROM input_0 t JOIN input_1 s USING (nct_id)
WHERE is_nordic AND site_status = 'RECRUITING'
"""
"""Eligibility and every recruiting Nordic site, without judgement, scores or ranking."""

TRIAL_RATES = """
WITH populations(country, population_m) AS (
    VALUES ('Finland', 5.64), ('Sweden', 10.59), ('Norway', 5.59), ('Denmark', 5.99)
), groups(cancer_group) AS (
    VALUES ('all'), ('lung'), ('pancreas'), ('liver'), ('breast'), ('colorectal'),
        ('prostate'), ('blood'), ('skin'), ('brain'), ('other')
), ctgov AS (
    SELECT DISTINCT t.nct_id AS id, s.country, g.cancer_group
    FROM input_0 t JOIN input_1 s USING (nct_id) CROSS JOIN groups g
    WHERE t.overall_status = 'RECRUITING' AND s.site_status = 'RECRUITING' AND s.is_nordic
        AND (g.cancer_group = 'all' OR list_contains(string_split(t.cancer_groups, ', '),
    g.cancer_group))
), ctis AS (
    SELECT ct_number AS id, p.country, 'all' AS cancer_group
    FROM input_2 CROSS JOIN populations p
    WHERE is_oncology AND CASE p.country
        WHEN 'Finland' THEN status_fi WHEN 'Sweden' THEN status_se
        WHEN 'Norway' THEN status_no WHEN 'Denmark' THEN status_dk END = 'ongoing, recruiting'
), counts AS (
    SELECT 'ClinicalTrials.gov' AS registry, g.cancer_group, p.country,
        count(c.id)::INTEGER AS trials, p.population_m::DOUBLE AS population_m
    FROM populations p CROSS JOIN groups g LEFT JOIN ctgov c USING(country, cancer_group)
    GROUP BY ALL
    UNION ALL
    SELECT 'CTIS', 'all', p.country, count(c.id)::INTEGER, p.population_m::DOUBLE
    FROM populations p LEFT JOIN ctis c USING(country) GROUP BY ALL
), pooled AS (
    SELECT * FROM counts UNION ALL
    SELECT registry, cancer_group, 'SE+NO+DK', sum(trials)::INTEGER, sum(population_m)
    FROM counts WHERE country <> 'Finland' GROUP BY registry, cancer_group
), rates AS (
    SELECT *, trials / population_m AS per_million FROM pooled
)
SELECT r.*, CASE WHEN r.country <> 'Finland' THEN f.per_million / nullif(r.per_million, 0) END
    AS rate_ratio_fi,
    'Eurostat demo_pjan, 1 Jan 2025' AS population_source
FROM rates r JOIN rates f ON r.registry = f.registry AND r.cancer_group = f.cancer_group AND
    f.country = 'Finland'
"""
"""Country-site rates; pooling sums country counts, including multinational trials."""
