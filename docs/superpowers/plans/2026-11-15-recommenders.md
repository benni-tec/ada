# Recommenders: one input, several models, saved cases as data

> **Planned, not started (2026-11-15).** Builds on the statistical models and the patient pathway model (`2026-11-14-statistical-models-implementation.md`, branch `pathway-model`, PR #7).
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the thing a doctor uses is a **recommender**, not a model. A recommender has its own input schema and a list of models. A doctor fills in the input once and sees one section per model: the pathway timeline (trigger, deadlines, days behind, survival second) and the clinical trials the patient could join. Every input is saved as a **case**, and the cases are an ADA data source, so a wellbeing county can see how fast its pathways move, step by step, and whether that improves.

**Why:** Denmark registers every pathway step and monitors the times nationally; Sweden publishes the share within target per region. Finland has no trigger, no clock and no measurement. The recommender brings the clock to the doctor and the measurement to the county.

- **Doctors:** a list of open cases sorted by deadline status (overdue, due this week, on track). Exact; no hazard ratio.
- **Administration:** dashboards per county and step: share within target, median days, the bottleneck step, the trend, and an alert when a step slips.

**Data rule (unchanged):** synthetic data only; the red banner stays. Cases are pseudonymous ids with dates, never a person. A real deployment would run inside a wellbeing county, which may use its own data for management.

**Paths:** `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`.

## Decisions

1. **The input schema is the recommender's own, and must cover its models.** The author defines the fields; the build refuses a schema that does not include every field a model requires, with a type every value of which the model accepts. Extra fields (county, referral source, anything the county wants to track) are allowed: they are saved with the case and appear in the data source, and no model sees them. A model receives only the fields it declared.
2. **Field compatibility is checked, not assumed.** A field is `{name, type: text | number | integer | date | boolean | enum | enum_list | day_map, levels?, required, label, help}`. A model's requirement is satisfied when the schema field has the same name and type and, for an enum, its levels are a subset of the levels the model accepts (so the form can never produce a value the model refuses). Two models needing the same field with incompatible declarations make the recommender invalid; the error names both.
3. **Cases, not submissions.** A pathway grows over weeks. A case has a pseudonymous id, the input fields, and dated **events** per pathway step; each update adds events. The latest input is the case's state.
4. **Inputs are stored, outputs are recomputed** from the input and the pinned model versions. Exception: the trial matcher stores the trial ids it showed, since the trial list changes.
5. **Trial matching is structured only:** condition (site), recruiting status, a site in Finland or the Nordics, age range, sex. The eligibility text is shown, not judged. An LLM pass over eligibility text is a later, reviewed addition.
6. **The doctor's list lives on the recommender page;** the county dashboards are ordinary ADA dashboards over the cases source.
7. **Survival estimates never rank patients.** The list sorts by deadlines only (scheduling); survival appears per case as today and in the population view. Ranking by a survival estimate would be clinical prioritisation and a medical device (MDR Rule 11).

## Global Constraints

- Hexagonal layout and frozen-code rules from `docs/contracts.md`; models, ports, `tables.py` and migrations change in an integration step.
- Migration `0016_recommenders.py`, down `0015`. Add it to the migration list in `contracts.md`.
- The "Statistical models" contract changes: an evaluation through a recommender saves the case (input and events), never the output. A model evaluated on its own (`evaluate_model`) still stores nothing.
- No network in tests. The ClinicalTrials.gov data comes in through an ADA source (`url`, JSON), not from the backend at evaluation time.
- Checks: `CI=1 mise exec -- moon run backend:lint backend:format backend:test frontend:lint frontend:typecheck frontend:test`. Regenerate the client after REST changes.
- Never push to `main` without asking: it deploys.

## Task 1: The model interface

**Files:** `B/core/models/recommenders.py`, `B/core/services/recommenders/models.py`, `T/test_recommenders.py`.

- [ ] `InputField{name, type, levels, required, label, help}` and `InputSchema{fields}`.
- [ ] A `RecommenderModel` protocol: `kind`, `requires(version) -> InputSchema` (the fields it needs, with the levels it accepts), `evaluate(version, values) -> Section`. A `Section{kind, title, body}` where `body` is the model's own result type (a tagged union in the API).
- [ ] `patient_pathway` adapter: `requires` derives the fields from the spec (site, sex, age group, education, route, stage, intent, modality from the terms; presentation from the criteria ids; days from the steps); `evaluate` builds `EvaluationInputs` and calls today's `evaluate`.
- [ ] `check_schema(schema, requirements) -> None`: Decision 1 and 2, with errors that name the field and the model. Tests: missing field, wrong type, enum levels not a subset, two models disagreeing, extra fields allowed.

## Task 2: The trial matcher

**Files:** `B/core/services/recommenders/trials.py`, `T/test_recommenders.py`; data through MCP.

- [ ] Data: register the ClinicalTrials.gov API v2 as `url` JSON sources (recruiting interventional studies with a site in Finland, Sweden, Norway or Denmark, for lung, colorectal and pancreatic cancer), and a data step `recommender_trials` with `nct_id, title, site (lung | colorectal | pancreas), phase, status, countries, min_age, max_age, sex, eligibility, url`.
- [ ] A trial matcher version pins that operator and run, like the NORDCAN baseline. `requires`: site, sex, age group. `evaluate`: the trials whose site, sex and age range match and that recruit; sorted by country (Finland first), then phase. Shown with the eligibility text, not judged.
- [ ] Tests on fixed rows: age band at the edge of a range, sex "all", no trial found.

## Task 3: Recommenders and cases (integration step)

**Files:** `B/core/models/recommenders.py`, `B/core/ports/repositories.py`, `B/adapters/db/tables.py`, `B/adapters/db/migrations/versions/0016_recommenders.py`, `B/adapters/db/…`, `B/adapters/memory/…`, `B/core/services/recommenders/service.py`, `T/test_recommenders.py`, `T/test_database.py`.

- [ ] `Recommender{id, project_id, name, description, schema, models: [{kind, model_id, version}], created_by, created_at, revision}`. Creating or changing one runs `check_schema`.
- [ ] `Case{id, recommender_id, reference (pseudonymous, given by the user or generated), county, values, created_at, updated_at}` and `CaseEvent{case_id, step, day, recorded_at}`. Updating a case writes the new values and the events that changed.
- [ ] `RecommenderService`: `create`, `update`, `get`, `list`, `recommend(recommender_id, values, case_id?) -> Recommendation` (saves the case, returns one section per model), `cases(recommender_id, filter)`, `worklist(recommender_id)` (open cases with their deadline status, sorted).
- [ ] Tables, migration, repositories (SQL and memory). Tests: create, refuse an uncovered schema, recommend saves the case and not the output, an update adds events, the worklist sorts overdue first.

## Task 4: Cases as a data source

**Files:** `B/core/models/sources.py` (`AccessKind.RECOMMENDER`), a reader in `B/adapters/sources/`, `T/test_recommenders.py`.

- [ ] `access_kind "recommender"`, address = the recommender id, `options.table` = `cases` or `events`. The reader produces a snapshot like any other source (the cases table: reference, county, every schema field, created and updated; the events table: reference, county, site, step, day, days in step, target, within target). Freshness `push`: a saved case marks the source stale.
- [ ] Data steps registered with the recommender (through MCP, Task 6): share within target per county, site, step and month; median days per step; the bottleneck step per county.
- [ ] Tests: a snapshot of the memory cases, the declared schema includes the extra fields, a new case makes the source stale.

## Task 5: REST, MCP and the agent

**Files:** `B/entrypoints/http/routers/recommenders.py`, `B/entrypoints/mcp/tools/recommenders.py`, `docs/contracts.md`, `T/test_api.py`.

- [ ] REST: `GET/POST /projects/{id}/recommenders`, `GET/PATCH /recommenders/{id}`, `POST /recommenders/{id}/recommend` (body `{values, case_id?}`), `GET /recommenders/{id}/cases`, `GET /recommenders/{id}/worklist`.
- [ ] MCP: `create_recommender`, `get_recommender`, `recommend`, `list_cases`, `worklist`. The verbs list in `test_api.py` gains `recommend`.
- [ ] Contracts: a "Recommenders" section; the statistical models section's storage line changes as in Global Constraints.

## Task 6: Synthetic cases and the county dashboards (MCP)

- [ ] A generator (a script in `services/backend/scripts/`, or an MCP-driven batch) that creates a few hundred synthetic cases across the wellbeing counties and the three sites: per-step days drawn around Finland's figures (Yle MOT for lung; the targets elsewhere, said so), county spread scaled by Sotkanet 5033 (referrals over 21 days), and a gentle improvement over the months so the trend has something to show. Labelled synthetic in every case reference and in the dashboard text.
- [ ] Register the cases and events as sources, build the data steps of Task 4, and a dashboard "Pathway times by county": share within target per step (bars per county), median days per step against target, the bottleneck step, the monthly trend, and an alert rule on a falling share. The queue-growth alert on main is the pattern.

## Task 7: The recommender page

**Files:** `F/routes/projects/$projectId/recommenders/…`, `F/components/recommenders/…`, `F/lib/api/recommenders.ts`, `F/test/recommenders.test.tsx`.

- [ ] A page per recommender with the line tab bar: **Recommend** (the form generated from the schema, then one section per model: the pathway section is today's Evaluation result; the trials section lists matches with phase, countries, eligibility and a link), **Open cases** (the worklist, overdue first, each row opening its case), **Setup** (the schema and the models, with what each model requires and which extra fields the author added).
- [ ] The Models page stays for authors; the sidebar shows Recommenders above Models.
- [ ] Tests: the form shows every schema field, a section per model renders, the worklist order.

## Task 8: The demo

- [ ] Update the slides and the demo profiles: profile 1 through the recommender (timeline plus two trials), the worklist with the generated cases, the county dashboard with the trend.
- [ ] Pitch line: "Norway, Sweden and Denmark start a clock when cancer is suspected and measure every step. Finland does neither. We bring the clock to the doctor and the measurement to the wellbeing county."

## Review Focus

1. **The schema covers its models.** No recommender saves with a field missing or a level a model would refuse; extra fields reach the data source and no model.
2. **Outputs are not stored.** A case holds input and events; recomputing gives the same timeline section for the same versions.
3. **The worklist never sorts by survival.**
4. **The cases source is an ordinary source:** snapshots, lineage, freshness; dashboards over it carry their lineage to the recommender.
5. **Synthetic is said everywhere:** case references, the dashboard text, the banner.
