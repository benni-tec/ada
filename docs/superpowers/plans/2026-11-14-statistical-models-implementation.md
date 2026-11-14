# Statistical models and the patient pathway model: implementation plan

> **Planned, not started (2026-11-14, revision 3).** This replaces the task sketch in Part 3 of `2026-11-14-statistical-models.md`. The model follows the v2 specification in `2026-11-14-statistical-models-grounding.md`: a Nordic baseline, the fast-track trigger and deadlines as the lead output, a DAG with one parameter per arrow, two toggles instead of a Monte Carlo, and a Finland residual instead of recalibration. Read that document first.

> **Built on 2026-11-14 (branch `pathway-model`, migration `0015`): lung, colorectal and pancreas, v1.** What is in the code: the resource and its versions (Tasks 2, 3), the evaluator with the trigger, the deadlines, the days behind target, survival per setting, levers and flags (Task 4), REST and MCP with the agent (Task 5), the Models page with its three tabs and the banner (Task 7). The baseline is read from ADA's NORDCAN operator (`op_fbd206c1…`) and cited by operator and run; the three Swedish pathway documents are registered and fetched as ADA document sources (ids on their citations); the other parameters ship in `core/services/statistical_models/pathway.py` with their provenance (the Norwegian pages and the papers are HTML, which ADA reads through Context.dev, so registering them waits for a credit decision). Still to do: the Danish document (sst.dk refuses automated fetches), a stage-specific baseline, the excess share for the scale conversion, Finland's days per step for colorectal and pancreas, and the demo slides themselves (the profiles and the slides are in `2026-11-14-pathway-model-demo.md`; the slides are published at https://claude.ai/artifact/4LSDyw28ehwNQKTyhSsKNy). The checkboxes below are updated to match.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a project can hold **statistical models**: versioned, built from ADA operators and cited sources, with every parameter's provenance. Anyone can **evaluate** a model on one profile through REST, MCP, the in-platform agent or a form. An evaluation creates no run, snapshot or operator. The first model is the patient pathway model for colorectal and lung cancer. For one profile it says whether the presentation would start a Nordic fast-track pathway, when each step is due, how many days the pathway is behind target, and, second and graded, what that is associated with in survival. For the population it says how much of Finland's survival gap timing explains.

**Data rule (decided 2026-11-14):** ADA is for educational use and synthetic profiles, never patient data. A permanent red banner at the top of every page says so. Evaluations are ordinary tool calls: the in-platform agent may call `evaluate_model`, and sessions record the call like any other.

**Why this order:** the science gates the platform. Task 0 records the decisions still open. Task 1 produces the data, through MCP only. Tasks 2–7 build the platform and fill it; Task 8 prepares the demo.

**Architecture in one paragraph:**
- **A model version is a compiled, immutable artefact.** Its spec (DAG modules, terms, parameters with provenance, trigger criteria, targets, toggles, intended use) is validated when it is created. *Building* the version reads the pinned operator snapshots, converts HR scales, computes the Finland residual, and stores the resulting tables on the version.
- **Evaluation is a pure function in `core`:** `evaluate(compiled_version, inputs, today) → Evaluation`. No I/O, no DuckDB, no unit of work.
- **The entry points add no runs.** REST and MCP call the pure function and return the result; the session records the MCP call like any other.

**Paths:** `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`.

## Global Constraints

- Hexagonal layout and frozen-code rules from `docs/contracts.md`. Models, ports, `tables.py` and migrations change in an integration step. Coordinate with the platform agent before starting.
- Migration `0015_statistical_models.py`, down `0014` (built first; functions and scenarios take the next numbers). Add it to the migration list in `contracts.md`.
- New backend dependency: `numpy`. Nothing else. No SciPy, no draws: intervals come from the CIs directly.
- **An evaluation creates no run, snapshot, operator or widget**, and touches no DuckDB. This is for performance and simplicity; privacy rests on the data rule and the banner.
- Parameters enter the model only from an ADA operator (pinned snapshot) or a registered ADA source with a quoted passage. No literal number in code or in a spec without provenance.
- No network in tests.
- Data work (Task 1) is MCP-only and asks before spending Context.dev credits or calling hackjunction.app.
- Checks: `CI=1 mise exec -- moon run backend:lint backend:format backend:test frontend:lint frontend:typecheck frontend:test`. Regenerate the client after REST changes.
- Commits in the repo's style, with the Claude co-author trailer. Never push to `main` without asking: it deploys.

## Review Focus

1. **No runs.** Evaluations through REST, MCP and the in-platform agent create no `runs`, `run_snapshots` or `operators` rows, and DuckDB is never opened. The banner shows on every route.
2. **Deadlines and days-behind are exact.** They depend only on the inputs and the target table, never on a toggle, and are tested against hand calculations.
3. **Each DAG arrow has exactly one parameter.** When stage is given, the two arrows into the stage mix are skipped and nothing else is. The pre-trigger delay arrow is applied whenever its toggle is on, stage given or not.
4. **The education term never appears in a per-patient figure.** It is in the model and in the analyst view; the patient-facing figures and levers leave it out.
5. **Provenance is complete:** every parameter, criterion and target resolves to a pinned operator snapshot or a source passage, with its country and its evidence grade.

## Task 0: Decisions before code

- [x] Confirm the reframing: the trigger and deadlines lead; survival second; Nordic baseline; educational use with synthetic profiles.
- [x] Confirm v1 sites: colorectal and lung; pancreas mostly `assumption`; liver not modelled.
- [x] Confirm the toggles: "Finland residual" (default on) and "days before the trigger count" (default off). The range is over the four combinations.
- [x] The in-platform agent may call `evaluate_model`, with the data rule and a global banner.
- [x] The Nordic difference-in-differences is dropped (grounding C7).
- [x] Decide whether the suspicion-stage criteria (Sweden's "misstanke") are modelled for colorectal too, or only for lung in v1. Recommended: lung only in v1; colorectal gets the pathway stage (well-founded suspicion onward).

## Task 1: Data (MCP only, project "Nordic cancer care")

Every item becomes a registered source and an operator the model reads. The passage each figure was checked against goes in the source's provenance.

- [x] **Trigger criteria, lung:** Norway (Helsedirektoratet, "Kriterier for henvisning til pakkeforløp", read 2026-11-14) and Sweden (RCC SVF lungcancer v1.4: "Misstanke" and "Välgrundad misstanke" lists). One row per criterion: `site, country, stage (suspicion | well_founded), text, source_id, passage`. Denmark when its document is downloaded by hand. The Swedish documents are ADA sources `01a1db1c-e73f…`, `01a1db1c-e785…`, `01a1db1c-e7b1…`.
- [x] **Standard times:** Norway (7 / 21 / 14 surgery or radiotherapy / 7 drugs; 42 / 35 total), Sweden (primary care 1 + 5 + 1 + 3 + 1 = 11 to pathway start; 40 drugs / 44 surgery or radiotherapy / 30 palliative from the decision to first treatment), Denmark to load. One row per `site, country, from_step, to_step, treatment_modality, days`. The target per step is the median across countries that define it, computed in an operator so the model page can show the spread.
- [x] **Nordic baseline:** NORDCAN 5-year relative survival by site and sex for Norway and Sweden (the strategy's "Nordic level"), 2020–2024, read from ADA's operator `op_fbd206c1d7b01ba0e8be5e09598bb74f` in run `01a1db11-d2fa-7782-95dd-aa41a3277464`. By age group (00-49 to 80-89) from the NORDCAN API directly. Still to load: **summary stage from Norway**.
- [ ] **Scale conversion:** NORDCAN observed and relative survival per site and sex for the Nordic baseline, to get `p` (the excess share of the hazard; grounding A1).
- [x] **Finnish comparison, for the residual:** NORDCAN Finland by site, sex and age band; the Finnish education mix per site (Statistics Finland or Zai's Table 1); the Finnish days per step (the Yle/Kuittinen medians: 155 total, > 50 patient, 41 primary care, 58 specialised; labelled preliminary and unpublished).
- [x] **Stage given education:** Zai 2025 (PMC12551501) stage IV vs I–III ORs per site and sex; lung from Figure 2. Recorded as applying to Norway's "distant" category, with a note on the split.
- [ ] **Stage given route:** a route-specific stage mix (Maringe-style). Nordic registries publish stage by route only partially; where missing, use McPhail 2022's emergency-presentation stage distributions for Denmark and Norway, graded `registry`.
- [x] **Direct education effect:** Zai's cancer-specific HRs adjusted for stage and treatment: all sites by sex; lung women 1.22; colorectal women 1.13. Men's lung and all pancreas use the all-sites HR, graded `assumption`.
- [x] **Post-trigger delay:** Hanna 2020 (PMC7610021): colectomy 1.06 (1.01–1.12), colorectal adjuvant 1.13 (1.09–1.17), lung surgery 1.06 (0.93–1.19), NSCLC adjuvant 1.01 (0.99–1.04); scale overall; valid for 4–16 weeks of total delay. Heiden 2021 (PMC8160592): the step at 12 weeks from the diagnostic CT, HR from the paper's survival table; scale overall. Pancreas: a range, graded `assumption`.
- [x] **Pre-trigger delay:** Sud 2020 (PMC7237184): 0.0056 per day for lung, pancreas and colorectal (5-year survival < 90 %); no CI, ±8 % as pseudo-SD; graded `assumption`.
- [x] **Education check:** Pokhrel 2010 (PMC2965870) Table 1, 5-year cause-specific survival by education per site and sex, 1996–2005.
- [ ] **The parameter table:** one operator, `pathway_model_parameters`: `module, arrow, term, level, estimate, ci_low, ci_high, scale (excess | cause_specific | overall | days), country, evidence_grade (standard | meta_analysis | cohort | registry | assumption), source_id, passage`.

## Task 2: Models and versions (integration step)

**Files:** `B/core/models/statistical_models.py`, `B/core/ports/…`, `B/adapters/db/tables.py`, `B/adapters/db/migrations/versions/0017_statistical_models.py`, `B/core/services/models/`, `T/test_statistical_models.py`.

- [x] Failing tests first: create, list, get; a version is immutable; spec validation refuses an arrow with no parameter or with two, a parameter without provenance, an unknown operator or source, a term whose reference level is not among its levels, a target step with no country, an empty `intended_use`.
- [x] Domain models:
  - `StatisticalModel{id, project_id, name, description, kind, latest_version}`;
  - `ModelVersion{model_id, version, spec, compiled, provenance, validation, intended_use, created_by, created_at}`.
  - `spec`: `outcome`; `structure: "relative_survival_dag"`; `modules[]` (arrow, parameter refs, `skip_when: ["stage"]` where it applies); `terms[]` (type, levels or range, reference, `display: patient | analyst`); `criteria[]` (site, country, stage, text); `targets[]` (site, from_step, to_step, modality, per-country days); `toggles[]` (name, default); `flags[]` (rule → action text).
- [x] Tables and migration. `compiled` is JSONB; it is small.
- [x] Service: `create_model`, `create_version(spec)`, `list_models`, `get_model`. A built version records `baseline: [{operator_id, snapshot_ids}]`.
- [x] Contracts: a "Statistical models" section in `docs/contracts.md`: the resource, immutability, the no-run rule, and that evaluations are ordinary tool calls.

## Task 3: Build (compile, convert, residual)

**Files:** `B/core/services/models/build.py`, `T/test_model_build.py`.

- [x] Failing tests first, with a fake operator reader and fixed tables:
  - the build pins the snapshot ids it read;
  - rebuilding from the same snapshots gives identical `compiled`;
  - the target per step is the median of the countries that define it;
  - overall-scale HRs are converted with the site's `p` and both values are kept;
  - the Finland residual per site and sex reproduces NORDCAN Finland for the average Finnish profile to 1e-3.
- [ ] Read the parameter table, criteria, targets, Nordic baseline, `p`, the Finnish comparison tables, at their latest snapshots, through the existing operator-read port.
- [x] Compute the residual: run the average Finnish profile (Finnish education mix, Finnish days per step, both toggles off) through the evaluator per site and sex, and solve the one factor on the excess hazard that lands it on NORDCAN Finland. Bisection; monotone. Store the factor and the pre-residual prediction, so the population view can show "Nordic → timing-adjusted → Finland".
- [x] Store `validation.residual` per site and sex.

## Task 4: The evaluator (pure, `core`)

**Files:** `B/core/services/models/evaluate.py`, `T/test_model_evaluate.py`.

- [x] Failing tests first:
  - **trigger:** each criterion fires alone; the result names the country and the criterion; an unclear X-ray fires nothing;
  - **deadlines:** from a trigger date, each deadline equals the target; status is `met`, `late_by`, `due_in` or `overdue_by` with the right number, against hand calculations;
  - **days behind:** per step, exact, independent of the toggles;
  - **stage given:** the two stage-mix arrows are skipped and nothing else is;
  - **pre-trigger toggle:** off → no effect; on → the per-day effect, whether or not stage is given;
  - **cap:** total post-trigger delay beyond 16 weeks is capped, with a warning;
  - **palliative intent:** delay terms off;
  - **monotone:** more days beyond target never raise survival; days at or under target change nothing;
  - **display:** the patient-facing contributions exclude every `display: analyst` term;
  - **range:** the stated range spans the four toggle combinations;
  - **speed:** under 20 ms per evaluation.
- [x] `evaluate(compiled, inputs, today) → Evaluation`:
  1. Validate inputs against the terms; unknown terms refused; missing optional terms take the reference with a warning.
  2. Trigger: match the presentation against the criteria per country and stage.
  3. Deadlines: from the trigger date (or from the step where the trigger would have fired), the targets per step and the whole-pathway deadline; status against `today`.
  4. Days behind target per step.
  5. Survival, per toggle combination: baseline by stage (or the stage mixture from education and route); post-trigger delay effect on the days beyond target, capped; pre-trigger effect if on; Finland residual if on; direct education term for the analyst view only. On target: the same with every remaining step at its target.
  6. Levers: each remaining step set to target, ranked by gain, with its evidence grade.
- [x] `Evaluation` holds `trigger{fired, stage, countries[], criteria[]}`, `deadlines[]`, `pathway[]` (days, target, gap, countries), `survival{now, on_target, by_toggle{}, range}`, `levers[]`, `flags[]`, `warnings[]`, `analyst.contributions[]`.
- [x] Round patient-facing figures to whole people out of 100; the analyst view keeps one decimal.

## Task 5: Evaluation endpoints (REST, MCP and the agent)

**Files:** `B/entrypoints/http/routers/models.py`, `B/entrypoints/mcp/tools/models.py`, `T/test_model_evaluation.py`.

- [x] Failing tests first: evaluate through REST, MCP and the in-platform agent's toolbox; no `runs`, `run_snapshots` or `operators` rows appear and DuckDB is not opened (a fake that fails when touched); the MCP call is an ordinary `tool_call` entry; the agent's toolbox lists `evaluate_model`, `list_models`, `get_model`; an invalid input is refused with the term and its allowed values.
- [x] REST: `POST /api/models/{id}/versions/{v}/evaluate` with `{inputs, today?, toggles?}`; `GET /api/models`, `GET /api/models/{id}`, `GET /api/models/{id}/versions/{v}`, and `GET …/population` for the per-site "Nordic → timing-adjusted → Finland" figures stored at build.
- [x] MCP and agent: `evaluate_model(model_id, version?, inputs, session_id)`, `create_model`, `list_models`, `get_model`. The `evaluate_model` description states the intended use: "educational; synthetic example profiles only, never patient data".
- [ ] Agent instructions: one line: use synthetic profiles; lead with the trigger and the deadlines; name each lever's evidence grade.

## Task 6: Validation runner

**Files:** `B/core/services/models/validate.py`, `T/test_model_validate.py`.

- [x] Residual check (from Task 3): per site and sex, the pre-residual prediction, NORDCAN Finland, and the residual factor.
- [x] Education check: the model's survival gap by education per site and sex (toggles default) against Pokhrel 2010's cause-specific survival by education.
- [x] Cross-model check: the delay-only effect against Hanna's worked examples (8 and 12 weeks of colectomy delay).
- [x] Results go into `version.validation`, each figure with the operator it came from, so a widget can show it.

## Task 7: Frontend

**Files:** `F/routes/__root.tsx` (or the app shell), `F/routes/models/…`, `F/components/models/…`.

- [x] **Global banner:** a slim red bar at the top of every route, not dismissible: "Educational use only. Do not enter patient data." In the root layout, with a test that it renders on the root, a dashboard and the models page. Check contrast in both themes.
- [x] **Model page, three tabs under the title, a full-width underline bar:** Model card, Evaluation, Population.
- [x] **Model card:** the DAG; the criteria lists per country; the targets per country and the median; the parameters with source, CI, scale and evidence grade; the validation (residual, education check, Hanna check); the intended-use statement; the TRIPOD+AI items that apply; "not validated on individual data".
- [x] **Evaluation form:** profile fields; the presentation as checkboxes grouped by stage (suspicion, well-founded suspicion), each naming its countries; stage and intent if known; the pathway as dates or days per step. State in React only, not in the URL.
- [x] **Evaluation result, in this order:**
  1. the trigger card: which stage fired, in which countries, which criteria; "Finland has no national trigger";
  2. the deadlines: clock start, each deadline with status, the next action;
  3. the pathway timeline: days per step against target, the gap, the patient interval greyed;
  4. survival as icon arrays, as it stands vs on target, with the two toggles and the range; levers with evidence grades;
  5. support to offer; read with care.

  The analyst toggle shows the log-hazard contributions, including education, with a note on why it is hidden by default.
- [x] **Population:** per site and sex, three bars: Nordic level, timing-adjusted, Finland, with the residual named; the days-per-step comparison Finland vs Sweden vs Denmark.
- [x] No widget for evaluations: widgets persist. A widget may show a model's structure, validation or population figures.

## Task 8: Demo and presentation

- [x] Three synthetic personas (lung only, in `2026-11-14-pathway-model-demo.md`; the colorectal and pancreas ones wait for their sites): lung, public route, nurse at first contact, suspicion criteria met, imaging late, now past the treatment deadline; colorectal, basic education, work-up on time, long wait for the MDT plan; pancreas, emergency presentation (mostly `assumption`, to show the grading). Stored as docs or a project text widget, never as real data.
- [x] Slides: the problem (Lundberg 2020, Yle MOT, Khalife 2025); the Nordic trigger and deadlines Finland lacks (Helsedirektoratet, RCC; Jensen 2017 for the effect); the DAG and why not a product of HRs (Westreich & Greenland); "timing explains about half the lung gap" with the residual (the population view); the education gap that survives adjustment (Zai, Pokhrel); what the model cannot claim (lead time, the paradox, where the effects come from); regulation. Check every ○ reference first.

## Open questions

- The Danish pathway document: downloaded by hand, with its times and criteria added as the third country.
- Norway's stage-specific survival by summary stage: available in "Cancer in Norway" tables? If only TNM, map I–II → localised, III → regional, IV → distant and say so.
- Is a route-specific stage mix available for Norway or Sweden? If not, McPhail's emergency vs non-emergency stage shares stand in.
- Colorectal trigger criteria (Norway, Sweden): to load; v1 may use the pathway stage only for colorectal (Task 0).
