# Case types, cases and recommenders

> **Planned, not started (2026-11-15, revision 2).** Builds on the statistical models and the patient pathway model (`2026-11-14-statistical-models-implementation.md`, branch `pathway-model`, PR #7). Trial matching is out of scope here: it is a model Felix adds later through the model interface of Task 1.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** three entities instead of one model on its own.

- A **case type** defines what a case holds: a schema of fields. "Suspected cancer pathway" is the first.
- A **case** is one instance of a case type, under a **key we set** (so it can point at a record in another system), with its values, its dated step events, and the results recommenders produced for it.
- A **recommender** operates on one case type and runs a list of models on a case. The case type's schema must cover the union of what the recommender's models need. Each run's result is stored on the case, so it can be viewed later.

Cases of a case type are an ADA data source: a wellbeing county can see, per step and over time, how fast its pathways move and whether that improves.

**Why:** Denmark registers every pathway step and monitors the times nationally; Sweden publishes the share within target per region. Finland has no trigger, no clock and no measurement. The recommender brings the clock to the doctor; the cases bring the measurement to the county.

- **Doctors:** the open cases sorted by deadline status (overdue, due this week, on track), from each case's latest result. Exact; no hazard ratio.
- **Administration:** dashboards per county and step: share within target, median days, the bottleneck step, the trend, and an alert when a step slips.

**Data rule (unchanged):** synthetic data only; the red banner stays. A key is a reference into another system, never a person: a key that looks like a Finnish personal identity code is refused.

**Paths:** `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`.

## Decisions

1. **Case types are independent of recommenders.** Several recommenders can operate on one case type; a case outlives any one of them.
2. **The schema must cover the models.** A field is `{name, type: text | number | integer | date | boolean | enum | enum_list | day_map, levels?, required, label, help}`. A model's requirement is met when the case type has a field with the same name and type and, for an enum, levels that are a subset of what the model accepts (so a case can never hold a value the model refuses). Creating a recommender, or changing a case type that recommenders use, is refused when a requirement is not met; the error names the field and the model. Extra fields are allowed: saved with the case, in the data source, never passed to a model. A model receives only the fields it declared.
3. **Schemas change compatibly.** A case type has a revision. While it has cases, a change may only add optional fields or add levels to an enum; anything else needs a new case type. Each case records the revision it was last saved under.
4. **The key is ours.** `key` is a string set by the caller, unique within the case type, 1–128 characters of `[A-Za-z0-9._:-]`, and never a Finnish personal identity code (`DDMMYY[-+A-FYXWVU]NNN[0-9A-Y]` is refused). Writing a case is an upsert by `(case_type, key)`. The internal id stays for foreign keys; the API addresses cases by key.
5. **Results are stored on the case.** A run stores `{recommender_id, model versions, the case revision it read, one section per model, created_at}`. Results are immutable history; the latest per recommender is the one shown. Recomputing is possible but not how history is read.
6. **Events, not only values.** A pathway grows over weeks. A case keeps dated step events (`step, day, recorded_at`); updating a case appends the events that changed. Values hold the latest state.
7. **The doctor's list lives on the recommender page;** the county dashboards are ordinary ADA dashboards over the cases source.
8. **Survival never ranks patients.** The list sorts by deadlines only (scheduling). Survival appears in a case's result and in the population view. Ranking by a survival estimate would be clinical prioritisation and a medical device (MDR Rule 11).

## Global Constraints

- Hexagonal layout and frozen-code rules from `docs/contracts.md`; models, ports, `tables.py` and migrations change in an integration step.
- Migration `0016_cases_and_recommenders.py`, down `0015`. Add it to the migration list in `contracts.md`.
- The "Statistical models" contract changes: a run through a recommender stores the case and its result. A model evaluated on its own (`evaluate_model`) still stores nothing.
- No network in tests.
- Checks: `CI=1 mise exec -- moon run backend:lint backend:format backend:test frontend:lint frontend:typecheck frontend:test`. Regenerate the client after REST changes.
- Never push to `main` without asking: it deploys.

## Task 1: Fields and the model interface

**Files:** `B/core/models/cases.py`, `B/core/services/recommenders/models.py`, `T/test_recommenders.py`.

- [ ] `Field{name, type, levels, required, label, help}`, `Schema{fields}`; value validation per type (an enum value among the levels, a `day_map` of step → non-negative integer, a date as ISO).
- [ ] A `RecommenderModel` protocol: `kind`, `requires(version) -> Schema` (the fields it needs, with the levels it accepts), `run(version, values) -> Section`, `columns(section) -> dict` (the flat figures the data source shows for this section). `Section{kind, model_id, version, title, body}`; `body` is a tagged union in the API, one member per kind.
- [ ] The `patient_pathway` adapter: `requires` derives the fields from the spec (site, sex, age group, education, route, stage, intent, modality from the terms; presentation from the criteria ids; days from the steps); `run` builds `EvaluationInputs` and calls today's `evaluate`; `columns`: trigger fired, clock start, days behind, per deadline its status and days over, survival now and on target.
- [ ] `check_coverage(schema, requirements)`: Decision 2. Tests: missing field, wrong type, enum levels not a subset, two models disagreeing, extra fields allowed.
- [ ] The model registry: kind → adapter, so Felix's trial matcher is one more entry.

## Task 2: Case types, cases and recommenders (integration step)

**Files:** `B/core/models/cases.py`, `B/core/models/recommenders.py`, `B/core/ports/repositories.py`, `B/adapters/db/tables.py`, `B/adapters/db/migrations/versions/0016_cases_and_recommenders.py`, `B/adapters/db/…`, `B/adapters/memory/…`, `T/test_recommenders.py`, `T/test_database.py`.

- [ ] `CaseType{id, project_id, name, description, schema, revision, created_by, created_at}`.
- [ ] `Case{id, case_type_id, key, values, schema_revision, created_at, updated_at}`, `CaseEvent{case_id, step, day, recorded_at}`, `CaseResult{id, case_id, recommender_id, case_revision, sections, created_by, created_at}` (the case's own revision counts its updates).
- [ ] `Recommender{id, project_id, case_type_id, name, description, models: [{kind, model_id, version}], created_by, created_at, revision}`.
- [ ] Tables (unique `(case_type_id, key)`), migration, SQL and memory repositories. Tests: the unique key, the round trip, the downgrade.

## Task 3: The services

**Files:** `B/core/services/cases/service.py`, `B/core/services/recommenders/service.py`, `B/core/services/ports/…`, `T/test_recommenders.py`.

- [ ] `CaseService`: `create_type`, `update_type` (Decision 3, and coverage for every recommender on it), `put_case(case_type_id, key, values)` (upsert; validates values; appends changed events; refuses a personal identity code as key), `get_case(case_type_id, key)` (values, events, results), `list_cases(case_type_id, filter)`.
- [ ] `RecommenderService`: `create` and `update` (coverage), `get`, `list`, `run(recommender_id, key, values?)`: with values, put the case first; then run every model on the case's values and store the result on the case. `worklist(recommender_id)`: open cases (no treatment start yet) with their latest result's deadline status, overdue first, then by days to the next deadline.
- [ ] Tests: a run stores one result with one section per model and the versions it used; a later run adds a result and keeps the first; a changed case type that would break a recommender is refused; the worklist order; the identity-code key is refused.

## Task 4: Cases as a data source

**Files:** `B/core/models/sources.py` (`AccessKind.CASES`), a reader in `B/adapters/sources/`, `T/test_recommenders.py`.

- [ ] `access_kind "cases"`, address = the case type id, `options.table`: `cases` (key, every schema field, created, updated), `events` (key, step, day, recorded_at), `results` (key, recommender, created_at, and each section's `columns`, prefixed by model kind). The declared schema is derived from the case type and the recommenders on it. Freshness `push`: a saved case or result marks the source stale.
- [ ] Tests: a snapshot of memory cases; extra fields appear; a new result marks the source stale.

## Task 5: REST, MCP and the agent

**Files:** `B/entrypoints/http/routers/cases.py`, `B/entrypoints/http/routers/recommenders.py`, `B/entrypoints/mcp/tools/…`, `docs/contracts.md`, `T/test_api.py`.

- [ ] REST: `GET/POST /projects/{id}/case-types`, `GET/PATCH /case-types/{id}`, `GET /case-types/{id}/cases`, `GET/PUT /case-types/{id}/cases/{key}`; `GET/POST /projects/{id}/recommenders`, `GET/PATCH /recommenders/{id}`, `POST /recommenders/{id}/run` (body `{key, values?}`), `GET /recommenders/{id}/worklist`.
- [ ] MCP: `create_case_type`, `put_case`, `get_case`, `list_cases`, `create_recommender`, `run_recommender`, `worklist`. The verbs list in `test_api.py` gains what is new.
- [ ] Contracts: a "Cases and recommenders" section; the statistical models storage line as in Global Constraints.
- [ ] A shipped "Suspected cancer pathway" case type and "Pathway recommender" (created with the pathway model, like `create_pathway_model` today), with a `county` field beside what the model needs.

## Task 6: Synthetic cases and the county dashboards (MCP)

- [ ] A generator (`services/backend/scripts/`) that puts a few hundred synthetic cases across the wellbeing counties and the three sites, keys `SYN-…`, and runs the recommender on each: per-step days drawn around Finland's figures (Yle MOT for lung; the targets elsewhere, said so), county spread scaled by Sotkanet 5033 (referrals over 21 days), and a gentle improvement over the months so the trend has something to show.
- [ ] Register the cases source, build the data steps (share within target per county, site, step and month; median days per step; the bottleneck step per county) and a dashboard "Pathway times by county" with an alert rule on a falling share; the queue-growth alert on main is the pattern. Every text widget says the data is synthetic.

## Task 7: The pages

**Files:** `F/routes/projects/$projectId/case-types/…`, `F/routes/projects/$projectId/recommenders/…`, `F/components/cases/…`, `F/components/recommenders/…`, `F/lib/api/…`, `F/test/recommenders.test.tsx`.

- [ ] A recommender page with the line tab bar: **Run** (a key, the form generated from the case type, then one section per model; the pathway section is today's Evaluation result), **Open cases** (the worklist; a row opens the case), **Setup** (the case type, the models and what each requires).
- [ ] A case page: values, the step events as a timeline, and the results history (latest first, each with the versions it used).
- [ ] A case type page: the schema and the recommenders on it.
- [ ] The Models page stays for authors; the sidebar shows Recommenders and Case types above Models.
- [ ] Tests: the form shows every schema field; a section per model renders; the worklist order; a case shows its results history.

## Task 8: The demo

- [ ] Profile 1 through the recommender under a key, the open cases with the generated ones, a case's result history, the county dashboard with the trend.
- [ ] Pitch line: "Norway, Sweden and Denmark start a clock when cancer is suspected and measure every step. Finland does neither. We bring the clock to the doctor and the measurement to the wellbeing county."

## Review Focus

1. **The schema covers its models,** at recommender creation and at every case type change; extra fields reach the data source and no model.
2. **Results are history:** a run adds a result with the versions it used; nothing overwrites one.
3. **Keys are ours and never a person:** upsert by key, unique per case type, identity codes refused.
4. **The worklist never sorts by survival.**
5. **The cases source is an ordinary source:** snapshots, lineage, freshness; dashboards over it carry their lineage to the case type.
6. **Synthetic is said everywhere:** keys, dashboard text, the banner.
