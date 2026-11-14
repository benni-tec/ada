# Nordic cancer trials

`ada seed-trials` idempotently registers project **Nordic cancer trials**, eight
sources, seven SQL data steps and a session recording each operator. No credentials
are needed. `ada seed-trials --refresh` forces all sources to fetch, then prints
exact row counts per step through a run. A failure is reported by the command;
successfully refreshed snapshots remain stored. Rerun to recover.

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
`sort=LastUpdatePostDate:desc`, `fields=NCTId,LastUpdatePostDate`, comparing totalCount
and the first study's last-update date. Publisher: U.S. National Library of Medicine;
landing page: https://clinicaltrials.gov; reuse licence unknown, unverified.

One CTIS REQUEST source per country POSTs to
`https://euclinicaltrials.eu/ctis-public-api/search`, with JSON headers and body
`{"pagination":{"page":1,"size":1000},"sort":{"property":"decisionDate","direction":"DESC"},"searchCriteria":{"msc":[246]}}`.
MSC codes are FI 246, SE 752, NO 578, DK 208. This search includes all therapeutic
areas and statuses; SQL selects oncology using C04. Rows are `data`; trialCountries
and therapeuticAreas remain JSON. While `pagination.nextPage` is true the reader
increments body `pagination.page`. Daily PROBE uses the same POST with size 1,
comparing `pagination.totalRecords`, `data.0.ctNumber`, `data.0.lastPublicationUpdate`.
Publisher: European Medicines Agency; landing page: https://euclinicaltrials.eu;
reuse licence unknown, unverified. Daily probes can miss changes that alter none
of their selected fields; force a refresh when a complete reread is needed.

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
statuses lag. A pending CTIS listing is not a Finnish recruiting site. The two
registries overlap and their counts must not be added. CTIS code meanings are
inferred from samples, not an authoritative codebook. Broad CT.gov search can
include non-cancer conditions. Basket trials can belong to several cancer groups;
groups are not additive or evidence of suitability for a particular patient.

Populations in millions: FI 5.64, SE 10.59, NO 5.59, DK 5.99, from Eurostat
demo_pjan, 1 January 2025 (https://ec.europa.eu/eurostat/databrowser/view/demo_pjan/default/table).
National 1 January 2026 figures are up to 0.7% higher. Per million residents is not per patient.
These tables make no eligibility judgement or treatment recommendation.

Local full-recording check (2026-11-15): CT.gov FI 98 (17.38/M), pooled SE+NO+DK
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

Find the project and its **Nordic cancer trials** session, then the recorded
operator whose note starts `case_trials:`. All seven notes start with their contract
name. In the seed integration, `TrialSteps` exposes every operator by that same name;
`seed.py` attaches dashboards and leaves a hand-over for monitoring.
