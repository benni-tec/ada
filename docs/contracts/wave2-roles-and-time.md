# Wave 2, workstream J: roles and time

What J defines, to be folded into `docs/contracts.md` at integration. It changes wave 1
code that others build on: the pipeline, source and schema code. G, H and I only read it.

## Changes to frozen code

All additive and backward compatible.

| File | Change |
| --- | --- |
| `core/models/time.py` | `Grain` (`year`, `quarter`, `month`): the calendar unit every period of a table spans |
| `core/models/schema.py` | `TimeRole.grain: Grain \| None = None`; docstrings of `TimeRole` and `GeoRole` (level `mixed`) |
| `core/services/ports/sources.py` | `SourceService.refresh_range(id, time_range) -> Snapshot \| None`, with a default body returning `None`, so implementations from before (test fakes) keep working and fall back to the whole source |

No table, migration, port in `core/ports` or route changed. `openapi.json` and
`schema.d.ts` are regenerated (the `Grain` enum and `TimeRole.grain`).

## Periods

A period is an `Interval`, both ends inclusive. A time role names the columns of a period's
first and last day; they must be `date` or `timestamp` columns. `grain` says what every
period spans; windows such as 2020–2024, or periods of mixed length, have none.

**A row is in a time range when its period and the range share at least one day.**
Periods are atomic: a range from June takes the whole year, and a range for 2024 shows the
window 2020–2024. A row without a period is in no bounded range. Alerts (I) keep ordering
periods by the time role's `start` column; the role's shape is unchanged.

`ada.core.services.schema.time` reads a source's own way of writing a period
(`parse_period`): `2024`, `"2024"`, `"2020-2024"` (also with an en dash or a slash),
`"2024Q1"`, `"2024M03"`, `"2024-03"`, `"2024-03-15"` (widened to its grain when one is
given). It also splits a range into the periods of a grain (`periods`), writes a period
for a request (`label`: `2024`, `2024Q1`, `2024M03`, or a format with `{year}`,
`{quarter}`, `{month}`), and names its snapshot (`period_key`: `period:<start>/<end>`).

### Mapping a source's period: the `period` shaping option

In `DataSource.options`, for JSON and CSV, applied after `fields`:

```json
"period": {"column": "year", "start": "period_start", "end": "period_end", "grain": "year"}
```

adds the period of each row as two ISO date columns, which DuckDB reads as dates.
`start`/`end` default to `period_start`/`period_end`; `grain` widens dates. Declare the two
columns as `date` and as the time role. In SQL the same is `make_date(year, 1, 1)` and
`make_date(year, 12, 31)`.

The `fields` option also gains the type `"json"`: a nested value (a GeoJSON geometry, a
list of ids) kept as its JSON text in one column.

## Time-range pushdown

A source declares how it takes periods in `options.pushdown`:

| Key | Meaning |
| --- | --- |
| `param` | A query parameter, repeated once per period (Sotkanet's `years`). It replaces parameters of that name in the address |
| `body` | Request sources: a dot path into the JSON body whose value becomes the list of periods (a PxWeb time selection, e.g. `query.2.selection.values`). Digits index arrays |
| `format` | Optional: how a period is written, with `{year}`, `{quarter}`, `{month}` |

Exactly one of `param` and `body`. Pushdown needs a declared schema with a time role that
has a grain; registration (and every update) refuses anything that cannot work: no time
role or grain, both or neither key, a body path that does not exist, a body path on a URL
source, a format that fails. The source must answer for exactly the periods asked for:
a row of another period, or without one, fails the fetch.

The source service rewrites the options (`params` or `body`) and calls the reader as
usual; readers need no notion of periods.

### What a run does with its time range

For each source operator, when the run's range has a start (`Runs._Planner._source`):

1. `SourceService.refresh_range(source, range)`. For a source with pushdown: the range is
   split into the grain's periods (an open end runs to the period containing today);
   stored periods are looked up by `period:<start>/<end>`; the missing and stale ones are
   fetched **in one request** and the answer is split by period; each is stored as a
   snapshot with `parameters_key = period:<start>/<end>` and `Snapshot.period` set. A
   period with no rows (a year not published yet) is stored as an empty table with the
   declared columns, so it counts as fetched. The result is one snapshot of the source
   operator, the **union** of the periods, cast to the declared columns and types, keyed
   `range:<digest of the periods' keys and content hashes>` and reused while those match.
   The run fixes the union like any snapshot.
2. Otherwise (`None`: no pushdown, or no start), wave 1: `refresh(source)` and the whole
   snapshot (`parameters_key = ""`).
3. In both cases, when the source operator has a time role and the range is bounded, the
   run filters the source's rows by the overlap rule (`PeriodFilterNode` in
   `pipelines/fusion.py`). For a union this changes nothing; for a whole source it is the
   filter. A source without a time role ignores the range.

The range enters a node's content identity only through the period filter or the period
snapshots below it, so materialized transforms are keyed per range exactly where the
range changed their input, and an operator that ignores the range keeps its key.

A run without a range (every widget outside a dashboard, `preview_operator`) reads the
whole source as in wave 1; the address of a pushdown source states what that is (Sotkanet:
the years in the address). `RunService.start` refuses a range that ends before it starts.

### Freshness by period

A stored period is fetched again when it is stale:

| Policy | Stale when |
| --- | --- |
| any, for the newest periods | older than `latest_period_ttl_seconds`, when set. The newest periods are those from the start of the latest stored period that has rows onwards (they include later, still empty periods) |
| `ttl` | older than `ttl_seconds` |
| `probe` | the probe's token changed. The probe runs at most every `ttl_seconds` (by `last_checked_at`, as for the whole source) and also before a first fetch, so the token stored is the one the data was fetched under. A changed token refetches the requested periods and retires every other current snapshot of the source (other periods, unions, the whole-source snapshot): they predate the change and are fetched again when next asked for |
| `manual`, `push` | never by age |

- A period fetched again always gets a new snapshot, superseding the old one, even when its
  content is the same: the snapshot's `fetched_at` is how the period's age is measured. It
  points at the same content-addressed file and has the same hash, so the union and
  everything downstream keep their identity. This differs from the whole source, where an
  identical refetch writes nothing.
- A forced `refresh` (after an edit of address or options, or by hand) and a whole-source
  `refresh` that sees a new probe token retire every stored period and union.
- Success is recorded with `record_check` in the caller's transaction and announced as
  `source.refreshed` (`changed` when any period's content differs). A probe moves
  `last_checked_at`; fetching periods alone does not, so it does not put off the whole
  source's scheduled refresh.
- Failure is recorded through `SourceCheckLog` and announced as `source.refresh_failed`, as
  in wave 1. When every requested period has a stored snapshot, those are served and the
  widgets show `is_stale`; a period never stored makes the run fail with the error.
- The scheduler is unchanged: it refreshes the whole-source snapshot of due sources.
  Periods are refreshed when a run asks for them.

### The worked example: Sotkanet

`SOTKANET_BREAST_SCREENING` has `"period": {"column": "year"}`, `"pushdown": {"param":
"years"}`, a time role with grain `year` on `period_start`/`period_end`, and a geography
role on `region` (system `sotkanet`, level `mixed`). A run for 2023–2024 asks
`...&years=2023&years=2024`; a later run for 2022–2024 asks for `years=2022` only.
`tests/test_time_pushdown.py` runs this against recorded answers.

## Roles checked before anything runs

All in `ada.core.services.schema.roles`, raising `Invalid` with every problem named.

- **Declarations** (`check_roles`): named columns exist; a period's ends are `date` or
  `timestamp`; a measure, its bounds and coverage are numbers; bounds come in pairs; a
  suppression flag is a boolean; a geography role names a code system and a level. Now also
  run on a source's declared schema at registration and update (with unique column names).
- **Bindings and Input defaults** (`check_compatible`), besides the column check: a slot
  with a time role needs a bound pipeline with a time role on the same columns and, when
  the slot has a grain, the same grain; a slot with a geography role needs one on the same
  column with the same system and level. A slot without roles takes anything with the
  columns. Checked in `RunService.start` and `PipelineService.add_input`.
- **Widgets** (`check_widget`, called by `WidgetService.create`): unknown types are not
  checked; known types need a table output and:

  | Type | Needs |
  | --- | --- |
  | `value` | `column` if given: exists and is numeric; else a measure or a numeric column |
  | `line-chart` | `x`, `series` if given: exist; `y` if given: numeric; else a measure or a numeric column other than x |
  | `table` | every name in `columns` exists |
  | `map` | a geography role whose level is not `mixed`; a GeoJSON column (`geometry`, or the spec's `geometry`) of type json or text; `label` if given exists; a value as for `value` |

  Columns not known yet (a source registered without a schema) are not checked; roles
  always are.

### The interval guard (`schema/intervals.py`)

**A transform whose SQL aggregates rows may not declare a measure with bounds.**
Aggregating means grouping (GROUP BY, GROUP BY ALL, HAVING), an aggregate function or a
window over rows (`avg(...)`, `sum(...) OVER ...`), or removing duplicates (DISTINCT,
UNION/INTERSECT/EXCEPT without ALL, PIVOT), anywhere that produces the output rows: the
main query, its CTEs, the subqueries and joins it reads from. A subquery that only picks
rows (`WHERE period_end = (SELECT max(period_end) FROM input_0)`) does not count.

Why refuse rather than trust: the interval of an aggregate is not an aggregate of the
intervals; the platform cannot tell a correct computation from `avg(lower)`, so bounds
after aggregation come only from a statistic operator. Declaring the measure without
`lower`/`upper` is always allowed, and the widget then draws no band. DuckDB parses the
SQL (`json_serialize_sql`, run through `AnalysisStore.run`); the module reads its syntax
tree. Only transforms that declare bounds are parsed.

## Geography

`ada.core.services.schema.geo` documents the code systems (`sotkanet`, `statfin`,
`iso3166_numeric`) and levels (`country`, `wellbeing_services_county`,
`collaborative_area`, `hospital_district`, `municipality`, `mixed`). Others are allowed.
Moving between systems or levels is always an explicit join with a mapping table.

### Reference data, registered as project data sources

Both are in `adapters/sources/examples.py` (`REFERENCE`); `EXAMPLES` is now the three data
sources plus these two, so `ada seed-demo` registers five sources.

| Source | Address | Columns | Licence |
| --- | --- | --- | --- |
| `SOTKANET_REGIONS` | `https://sotkanet.fi/rest/1.1/regions` | `sotkanet_id`, `category` (e.g. `HYVINVOINTIALUE`, `KUNTA`, `MAA`), `code` (Statistics Finland's code at that level), `name`, `name_fi`, `member_of` (JSON text) | CC BY 4.0, THL |
| `WELLBEING_COUNTY_BOUNDARIES` | Statistics Finland's WFS, layer `tilastointialueet:hyvinvointialue4500k`, GeoJSON in EPSG:3067 | `county_code` (`01`–`21`, `90`, `91`), `name`, `name_fi`, `geometry` (GeoJSON text) | CC BY 4.0, Statistics Finland |

The boundaries are generalised for 1:4,500,000 maps: about 100 kB for the 23 areas.

### Recipe: Sotkanet's measure by county, on a map

```sql
-- inputs: screening (Sotkanet), regions, boundaries
SELECT b.county_code, b.name, d.period_start, d.period_end, d.value, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id
```

with roles `{"geo": {"code": "county_code", "system": "statfin", "level":
"wellbeing_services_county"}, "time": {"start": "period_start", "end": "period_end",
"grain": "year"}, "measures": [{"value": "value"}]}`. Starting from the boundaries keeps a
county without a value on the map, as missing (Åland has no Sotkanet screening value).
For a mapping without a map, join the other way and drop the geometry.

## The map widget

`services/widgets/src/widgets/map/` builds `dist/map.html`.

- **Spec:** `value` (default: the first measure role, else the first numeric column),
  `geometry` (default `geometry`), `label` (default: a column `name`, else the code). The
  region code is the geography role's column.
- **Shows** each region at its latest period (`latestPerKey` in `lib/columns.ts`), coloured
  by five equal classes from the smallest to the largest value, on the sequential blue
  ramp (more is darker; flipped in dark mode). Suppressed regions are hatched, regions
  without a value grey; neither is ever a colour of the scale. A legend names the classes,
  "No data" and "Suppressed", and the period most regions show.
- **Access:** the map is one focus stop; the arrow keys step through the regions in
  alphabetical order and a status line reads name, value and interval; Escape clears it.
  A visually hidden table lists every region, value and period. Hover shows the same.
- **Markers:** scenario and stale come from the shared runtime, as for every widget.
- **Coordinates:** planar metres (EPSG:3067) are drawn as they are; longitude and latitude
  with east-west distances shortened by the cosine of the middle latitude. North is up.

**Boundaries come as data, not with the bundle.** The spec makes boundary shapes
reference data, registered as project sources, so a map's outlines carry their source,
fetch time and licence in the lineage like any number, and any region level or country
works without rebuilding the widgets. Bundled, Finland's counties would add about 100 kB
to `map.html` and to `any.html`, which an MCP host loads for every widget of any type,
against a bundle of 235 kB that is mostly React. As data they cost no second request: they
travel in the widget's own data response, about 100 kB for 23 regions. The price is that
a time series repeats each outline per period; filter the map's operator to the periods it
shows (the widget shows the latest anyway).

## Fixed on the way

`DataSources._fetch` added the new whole-source snapshot before superseding the current
one. PostgreSQL allows one current snapshot per operator and key
(`uq_snapshots_current`), so the first refetch with changed content would have failed
there; it now supersedes first. `tests/test_time_database.py` covers the period case on
PostgreSQL.

## Tests

| File | Covers |
| --- | --- |
| `test_time_periods.py` | Reading periods, splitting ranges, labels, the `period` option on JSON and CSV, the `json` field type, splitting answers by period |
| `test_time_pushdown.py` | Sotkanet pushdown, reuse and partial refetch (recorded), the probe unchanged and changed, the newest period's lifetime, empty periods, failures with and without stored periods, the whole source without a range, run filtering for NORDCAN (cannot filter), downstream keys per range, body pushdown, option validation |
| `test_time_database.py` | A refetched period on PostgreSQL |
| `test_roles_checks.py` | Declarations, bindings and Input defaults, widget requirements, the interval guard |
| `test_roles_geo.py` | Mapping Sotkanet ids to counties with the recorded reference data, a map widget over it, mixed levels refused |
| `widgets/map/map.test.tsx` | The map's model, rendering, legend, keyboard, the hidden table, markers |

New recordings: `sotkanet-3621-2022.json`, `sotkanet-3621-2024.json`,
`sotkanet-regions.json`, `statfin-wellbeing-counties.json` (all recorded 14 November 2026).
Updated: `test_sources_examples.py` expects the period columns on Sotkanet's first row.

## For integration

These are outside J's files:

- `entrypoints/mcp/tools/widgets.py`, `create_widget` docstring: add
  `- "map", a choropleth of one value per region: value (default: the first measure role,
  else the first numeric column), geometry (default "geometry": the region outlines as
  GeoJSON, joined from the boundaries reference source), label (default: a column "name").
  Needs a geography role at one level; shows each region's latest period.`
  and mention that a widget whose operator lacks what its type needs is refused.
- `entrypoints/mcp/tools/pipelines.py`, `add_transform` docstring: an aggregating step may
  not declare bounds on a measure.
- `services/widgets/src/widgets/any/any.tsx`: add `map: RegionMap` (from
  `@/widgets/map/map`) to `TYPES`, so MCP hosts render maps.
- `services/frontend/src/components/widget-card.tsx`: a height for `map` (about 420).
- `docs/contracts.md`: the widget spec table (add `map`), the Sources section (period
  snapshots and keys), and this file.

## Known limits

- Union snapshots are a cache keyed by content; they are retired only by a probe change or
  a forced refresh, so they accumulate like materialized transforms do.
- `refresh_range` lists the source operator's snapshots to find the newest period; fine
  for years, slow for thousands of periods.
- A range without a start is not pushed down (the source is read whole and filtered).
- `last_error` is cleared only by a fetch or probe that succeeds; a run whose periods are
  all fresh leaves an earlier error, and the widgets keep showing stale.
- Equal classes show the spread honestly but put most counties in the top class when one
  region is an outlier; a quantile option can come later.
