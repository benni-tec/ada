"""Geography: the code systems and region levels a geography role names.

A geography role says which column holds a region code, which code system the codes come
from and which level the regions are at. Two tables can only be compared region by region
when both match; moving from one system or level to another is always an explicit step in
the pipeline, a join with a mapping table registered as a project data source.

The names below are the ones the platform's own reference data uses. Others are allowed:
a role is a declaration, and an agent may meet a system nobody listed here.

Code systems:

`sotkanet`
    Sotkanet's numeric region ids, e.g. 961 for East Uusimaa and 658 for the whole country.
    One id space for every level.
`statfin`
    Statistics Finland's classification codes, e.g. "01" East Uusimaa, "90" City of
    Helsinki, "91" Åland for the wellbeing services counties. PxWeb tables prefix them
    ("HVA01"); strip the prefix in SQL to map them.
`iso3166_numeric`
    Countries by ISO 3166 numeric code, e.g. 246 for Finland; NORDCAN uses these.

Levels:

`country`, `wellbeing_services_county` (the 21 counties plus Helsinki and Åland),
`collaborative_area` (the five areas survival is published for), `hospital_district`,
`municipality`, and `mixed` for a column that holds regions of several levels, as
Sotkanet answers for municipalities, counties and the whole country at once.

Mapping recipe: register the mapping (Sotkanet's regions endpoint relates its ids to the
Statistics Finland codes, ada.adapters.sources.examples.SOTKANET_REGIONS), then join it in
a transform and declare the new role:

    SELECT r.code AS county_code, d.period_start, d.period_end, d.value
    FROM input_0 AS d JOIN input_1 AS r ON r.sotkanet_id = d.region
    WHERE r.category = 'HYVINVOINTIALUE'

with roles {"geo": {"code": "county_code", "system": "statfin",
"level": "wellbeing_services_county"}, ...}. For a map, start from the boundaries
(WELLBEING_COUNTY_BOUNDARIES) and join the rest to them, so a county without a value is
still drawn, as missing:

    SELECT b.county_code, b.name, d.period_start, d.period_end, d.value, b.geometry
    FROM input_2 AS b
    LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
    LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id

Moving up a level (municipalities to counties) is an aggregation: counts add up, rates and
shares do not, and confidence intervals never carry over.
"""

SOTKANET = "sotkanet"
STATFIN = "statfin"
ISO3166_NUMERIC = "iso3166_numeric"

COUNTRY = "country"
WELLBEING_SERVICES_COUNTY = "wellbeing_services_county"
COLLABORATIVE_AREA = "collaborative_area"
HOSPITAL_DISTRICT = "hospital_district"
MUNICIPALITY = "municipality"
# The code column holds regions of several levels; filter to one before comparing them.
MIXED = "mixed"
