# Nordic cancer trials

`ada seed-trials` idempotently registers project **Nordic cancer trials**, eight registry
sources plus hospital pages, eleven SQL data steps and a session recording each operator. No credentials
are needed to register sources. `ada seed-trials --refresh` fetches sources, then prints
exact row counts per step through a run. A failure is reported by the command;
successfully refreshed snapshots remain stored. Rerun to recover.
A failed web page refresh is reported without aborting dashboard, session and monitor creation (steps that read a page without any snapshot report as unavailable); a watched page refetches only when Context.dev sees a change, so rerun the seed to retry it. Registry refresh failures remain fatal.

**Trial doors: Nordic cancer trials Finland lacks** shows registry trial rates,
recruiting Nordic sites, trials without Finnish sites and pending Finnish CTIS
listings. **Open cancer trials near you** lists recruiting trials and sites with
distances and registry eligibility text to discuss with an oncologist. Both
dashboards attach to the seed session; the command prints their IDs.

## Sources

One ClinicalTrials.gov URL source per Finland, Sweden, Norway and Denmark uses
`https://clinicaltrials.gov/api/v2/studies`. The address has `query.locn=<Country>`,
`query.cond=cancer+OR+neoplasm+OR+tumor+OR+carcinoma+OR+lymphoma+OR+leukemia+OR+myeloma+OR+sarcoma+OR+melanoma+OR+glioma+OR+glioblastoma+OR+mesothelioma`,
`filter.overallStatus=RECRUITING`,
`filter.advanced=AREA%5BStudyType%5DINTERVENTIONAL`, `pageSize=1000`, and the explicit
field list in `trials/sources.py`. Arrays of phases, conditions, interventions and
locations remain JSON. Pagination passes `nextPageToken` as `pageToken`.
The daily PROBE repeats that query with `pageSize=1`, `countTotal=true`,
`sort=LastUpdatePostDate:desc`, `fields=NCTId,LastUpdatePostDate`, hashing the whole
probe answer, including the total count and an empty studies array when applicable.
Publisher: U.S. National Library of Medicine;
landing page: https://clinicaltrials.gov; reuse licence unknown, unverified.

One CTIS REQUEST source per country POSTs to
`https://euclinicaltrials.eu/ctis-public-api/search`, with JSON headers and body
`{"pagination":{"page":1,"size":1000},"sort":{"property":"decisionDate","direction":"DESC"},"searchCriteria":{"msc":[246]}}`.
MSC codes are FI 246, SE 752, NO 578, DK 208. This search includes all therapeutic
areas and statuses; SQL selects oncology using C04. Rows are `data`; trialCountries
and therapeuticAreas remain JSON. While `pagination.nextPage` is true the reader
increments body `pagination.page`. Daily PROBE uses the same POST with size 1,
hashing the whole probe answer, including the total count and an empty data array
when applicable.
Publisher: European Medicines Agency; landing page: https://euclinicaltrials.eu;
reuse licence unknown, unverified. Daily probes can miss changes that alter none
of their probe answers; force a refresh when a complete reread is needed.

## Data steps and columns

- `trials`: nct_id, title, overall_status, phase, conditions, cancer_groups,
  intervention_types, is_drug, sponsor, sponsor_class, sex, min_age_years,
  max_age_years, eligibility, recruiting_countries, has_fi_site, fi_recruiting,
  last_update, url. One trial per NCT ID across the four sources, choosing the latest
  last_update, then locations JSON to break ties consistently. Phase joins with `/`,
  conditions and intervention types with `; `, countries and groups with `, `.
  Groups: lung, pancreas, liver, breast, colorectal, prostate, blood, skin, brain,
  otherwise other; regexes match conditions. is_drug means DRUG or BIOLOGICAL.
  Ages convert years/months/weeks/days to years; absent ages remain NULL.
- `trial_sites`: nct_id, facility, city, country, site_status, lat, lon, is_nordic.
  Every site of those deduplicated trials, including non-Nordic and closed sites.
- `trial_doors`: nct_id, title, phase, cancer_groups, is_drug, sponsor, sponsor_class,
  open_countries, nearest_facility, nearest_city, nearest_country, km_helsinki,
  km_kuopio, km_oulu, url. A door has an open SE/NO/DK site and **no Finnish site
  in any status**. Nearest facility is relative to Helsinki; each distance separately
  takes the nearest open neighbouring-country site.
- `ctis_trials`: ct_number, title, sponsor, sponsor_type, phase, conditions,
  is_oncology, status_fi, status_se, status_no, status_dk, decision_date, url.
  One CT number; latest overall decision date wins, country JSON breaks ties.
  Missing country statuses are NULL. Status labels are **[inferred]**: 2 authorised,
  recruitment pending; 3 ongoing, recruitment pending; 4 ongoing, recruiting;
  5 ongoing, recruitment ended; 6 halted; 7 suspended; 8 ended; 11 not authorised.
  Unknown codes retain their value as `unknown (<code>)`.
- `ctis_finland_pending`: ct_number, title, sponsor, sponsor_type, phase, status_fi,
  recruiting_in, decision_date, url. Oncology trials listing Finland with code 2 or 3;
  recruiting_in lists SE/NO/DK countries with code 4.
- `trial_rates`: registry, cancer_group, country, trials, population_m, per_million,
  rate_ratio_fi, population_source. CT.gov counts distinct trials per country with
  overall RECRUITING and at least one RECRUITING site there, for all and each group.
  CTIS counts oncology country code 4, for all only. Every Nordic country has a row
  even at zero; SE+NO+DK sums country counts and populations (a multinational trial
  can count in several countries). rate_ratio_fi is FI's rate divided by the row's
  rate, NULL for FI or a zero denominator.
- `case_trials`: see below.

Distances are great-circle kilometres, radius 6371 km, from Helsinki
(60.1699,24.9384), Kuopio (62.8924,27.6770), Oulu (65.0121,25.4651).
Missing coordinates yield NULL distances; no route or travel-time claim is made.

## Definitions and caveats

Recruiting means the registry's site status, not confirmed availability. Site
statuses lag. The `trial_site_changes` table suppresses `trial_left_list` and
`nordic_site_closed` removals for a source when its newest snapshot contains fewer
than half as many trials as its previous snapshot; additions still count. A pending CTIS listing is not a Finnish recruiting site. The two
registries overlap and their counts must not be added. CTIS code meanings are
inferred from samples, not an authoritative codebook. Broad CT.gov search can
include non-cancer conditions; the trials step keeps only conditions matching the
cancer regex in `steps.py`. Basket trials can belong to several cancer groups;
groups are not additive or evidence of suitability for a particular patient.

Populations in millions: FI 5.64, SE 10.59, NO 5.59, DK 5.99, from Eurostat
demo_pjan, 1 January 2025 (https://ec.europa.eu/eurostat/databrowser/view/demo_pjan/default/table).
National 1 January 2026 figures are up to 0.7% higher. Per million residents is not per patient.
These tables make no eligibility judgement or treatment recommendation.

Full-recording check (2026-11-15, before the condition filter, which removes 3 of
125 Finnish, 9 of 283 Swedish, 4 of 196 Norwegian and 17 of 334 Danish CT.gov trials
as non-cancer): CT.gov FI 98 (17.38/M), pooled SE+NO+DK
32.25/M, RR 0.539; CTIS FI 71 (12.59/M), pooled 18.63/M, RR 0.676;
39 Finnish CTIS oncology trials pending. Doors: 501 all cancers, 80 matching
lung/pancreas/liver conditions. The older analysis reported 87 for that subset;
its exact classification inputs are unavailable, so the difference remains unverified.

## For case models

`case_trials` is one row per (trial, RECRUITING Nordic site), with columns:
nct_id, title, phase, overall_status, conditions, cancer_groups, sex, min_age_years,
max_age_years, eligibility, recruiting_countries, facility, city, country, lat, lon,
km_helsinki, km_kuopio, km_oulu, url. Eligibility is the registry's text as written;
no score, ranking or eligibility judgement is added. Each distance describes that
row's site, not the trial's nearest site.

Find the project and its **Nordic cancer trials** session, then the most recently
recorded operator whose note starts `case_trials:` (a reseed after a SQL change
records the rebuilt step again). Every step note starts with its contract name.
In the seed integration, `TrialSteps` exposes every operator by that same name;
`seed.py` attaches dashboards and leaves a hand-over for monitoring.

The checked-in seven CT.gov recording records all pass the condition filter; their
counts are unchanged (including two recruiting Finnish trials).

`county_cities` (county, city) names, for each wellbeing services county, the city its
distances are read from: the nearest of Helsinki, Kuopio and Oulu, the cities of the km_
columns.

## Patient level: the trial matcher

The dashboards are the national picture. For one patient, the seed puts a trial matcher
model (docs/contracts.md "Cases") on a "Cancer trial candidate" case type in this project
(or a type the project already has that covers it; the agent instructions name the one it is
on), running on every save of a case. It reads `case_trials` and `county_cities` whenever it runs,
keeps the trials of the case's cancer group only, shows sex and age limits without applying
them, and sorts by distance from the county's city. The agent instructions send patient
questions through it: save a case with `set_case`, answer from the matcher's result. A reseed
that rebuilds the steps gives the matcher a new version reading the new ones. Any project can
add its own matcher with `create_trial_matcher` (e.g. on the cancer pathway case type).

## Hospital and sponsor pages

`ada seed-trials` also registers 14 daily Context.dev Markdown scrape sources:
HUS, Pirha's Finnish list (not its English duplicate), FICAN East/KYS,
FICAN West/Tyks; Karolinska's seven kpeks unit lists, KI Nordic SBRT,
Cancerstudier i Sverige; and OUS-research's Flatmark list. Addresses and page
metadata are seed data in `trials/pages.py`. Web refreshes need a Context.dev key.
With `ADA_PUBLIC_URL`, the monitoring seed watches these and sponsor pages;
without it their daily / seven-day TTLs remain. Watching changes freshness to push.

- `hospital_trials`: page_name, hospital, country, trial_id, id_kind, section,
  snippet. SQL splits Markdown into lines, takes NCT, EU CT (20xx-5xxxxx-xx-xx)
  and older EudraCT identifiers, carries the nearest preceding Markdown heading,
  and keeps the first occurrence per (page, ID). Snippets are at most 400 characters.
  No model runs for hospital parsing. Pages without identifiers, including kpeks
  and FICAN West, currently yield no rows; acronym/title-only rows are not parsed.
  An accordion label rendered as plain text is not a heading, so section may be
  the broader page heading. Inclusion in a list does not establish current recruitment.
- `hospital_trial_gaps`: gap_kind, nct_id, title, page_name, facility, city,
  country, section, snippet. `hospital_only` means a Finnish page lists an NCT
  absent from this CT.gov pull or with fi_recruiting false. `registry_only` means
  a Finnish recruiting registry site has no matching NCT on any Finnish page.
  These rows include facility/city; hospital-only rows use the page's hospital
  as facility and NULL city. These are coverage discrepancies, not confirmed errors:
  the registry pull is restricted and hospital lists are incomplete.
- `sponsor_sites`: nct_id, overall_status, facility, city, country, site_status.
  After `--refresh` reads the registries, up to `MAX_STUDY_PAGES = 200` sources
  are registered by NCT source name, ordered by NCT ID, for door trials or trials
  recruiting in Finland with AstraZeneca, MSD/Merck Sharp & Dohme, or Pfizer as
  lead sponsor. Merck KGaA is excluded. Existing sources are retained on reruns.
  Each extracts only FI/SE/NO/DK sites exactly as stated, with missing values NULL.
  These values are **model-extracted**, marked in source provenance, and may be
  incomplete or incorrect; confirm them on the linked sponsor page. Unwatched
  sponsor pages refresh at most every seven days; a watched page refetches when
  Context.dev reports a change (about 5 credits each time).

The monitoring dashboard includes hospital rows (Finland first), discrepancies,
and sponsor sites. The patient table reads only `case_trials`, so a failed page
scrape cannot block it. Reseeding updates dashboard slots
when their generated operators change.

`--refresh` reads registries first, then spaces web refresh starts by at least
7.5 seconds (`WEB_REFRESHES_PER_MINUTE = 8`). A full web refresh costs about
14 + 5 × study-page count credits (at the cap: 1,014); hospital scrapes cost one,
extracts about five each. Fresh sponsor snapshots are reused. The project's daily
web budget can stop a refresh; completed snapshots persist. Monitors and scheduled
refreshes have their own lifecycle; the seed's pacing applies to its refresh loop.

kpeks needs a full browser User-Agent and changes today's date in its footer.
The current web reader exposes neither target headers nor a content selector, so
access through Context.dev remains unverified and daily footer change noise is
accepted. Footer changes do not affect SQL trial rows. HUS has navigation noise;
OUS includes a changing publication feed. A successful scrape of a block page
can look like an empty trial list, so missing rows are not proof a trial closed.

All hospital and sponsor page sources are watched when `ADA_PUBLIC_URL` is set;
locally they retain their TTLs. Page definitions expose exactly three monitor
intervals: `10min` (HUS, KYS/FICAN East, Tays), `hourly` (other Finnish hospital
lists), and `daily` (Swedish/Norwegian lists and sponsor study pages). These are
stored in `options.trial_page.interval` and passed to `SourceService.watch` as
`check_every`; a reseed re-watches a page whose monitor has another interval. Monitor check cadence
is separate from source TTL and does not imply a scrape on every check.

`hospital_trial_changes` compares the latest two stored snapshots of each Finnish
hospital page using the same SQL identifier parser. Columns: change_kind, page,
trial_id, hospital, country, id_kind, section, snippet, snapshot_at. Events are
`listed_by_hospital` and `unlisted_by_hospital`; one snapshot yields no events.
Footer/text edits without identifier changes yield no events. The monitoring rule
**A Finnish hospital page listed a new cancer trial** is info-level, keyed by
(page, trial_id), and checks when its upstream data changes.

Research code can call
`await register_trial_page(request, project_id, url, name, kind, country)` from
`ada.entrypoints.cli.trials.seed` inside a request container for an already seeded
project. `kind` is `hospital_list` or `sponsor_study_page`; `country` is Finland,
Sweden, Norway or Denmark. It registers by (URL, kind), returns the `DataSource`,
and idempotently rebuilds shared unions, session entries, dashboards and watches.
Hospital metadata uses `name` as the hospital label; no URL-specific parser is
needed. New Finnish hospital pages also enter history and alert inputs. Since an
alert rule's measure cannot be changed, a changed hospital union replaces that
rule and retains the previous rule, disabled, with its alert history. The new rule
keeps the old one's severity, interval, data-age limit, alert pipeline and on/off state. Sponsor
URLs supplied this way need no known sponsor URL pattern. Registration does not
scrape; refresh the returned source separately. `--refresh` includes these added
pages in its paced web loop and credit estimate.

The trial matcher model (`trial_matcher`, docs/contracts.md "Cases") reads `case_trials`:
`create_trial_matcher` with that operator puts a matcher on the project's cancer case type.
