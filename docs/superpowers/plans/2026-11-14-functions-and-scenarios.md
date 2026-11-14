# Functions, scenarios and simulations: implementation plan

> **Planned, not started (2026-11-14). Reviewed by the platform agent: nothing clashes; its eight points are folded in below. Calls are inlined into concrete operators and scenarios are graph rewrites (the user's choice of option B), so runs and `run_snapshots` stay unchanged.** The order is the user's: functions first, then a
> scenario API, then simulations for the Nordic cancer care project from published effect
> sizes and other methods, shown as deviations from a baseline. Recommendations (an agent
> operator feeding a text widget) come after this. They are sketched at the end and
> planned separately.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- **Functions:** a project can define *functions*, parameterised pipelines with typed table inputs and typed scalar parameters, and apply them with a `call` operator.
- **Scenarios:** reproducible what-ifs built on those functions. A scenario is the same pipeline with other parameter values or other bound data, run side by side with the baseline, so every simulated number is marked and traceable to its assumptions.
- **This project:** policy levers (screening attendance, time to treatment, smoking, the education gradient, the Nordic survival gap) are turned into expected deviations from a projected baseline, with uncertainty from the published confidence intervals.

**Why:** the challenge scores actionability. A dashboard shows where Finland stands; a scenario shows what a measure would change and how sure we are. ADA already has most of the parts:
- `INPUT` operators;
- runs with `bindings`;
- `is_scenario` drawn by every widget;
- operator identity hashing, which caches the parts of a pipeline that a change does not touch.

**What is missing:**
- a way to parameterise a pipeline (only whole operators can be swapped today);
- reuse: the county map pipeline was built three times;
- any agent-facing way to run or compare scenarios: no MCP tool takes bindings, and bindings are keyed by slot name project-wide, so one view cannot hold both baseline and scenario.

**Architecture in one paragraph:**
- A **function** is a stored, versioned subgraph: its `INPUT` operators become the function's table inputs, and transforms may read typed **parameters** (`$name`, bound as DuckDB prepared-statement parameters, never spliced into SQL text).
- **Calls are inlined (the user's decision, option B).** Applying a function *expands* it, at definition time, into concrete operators: one per body step, with the call's inputs substituted for the body's `INPUT`s and the argument values stored on the operator (`TransformParams.parameters`, bound at execution, part of the identity).
  - They are ordinary operators, so a run records them under the same `run_id` as everything else, and `query_operator`, preview, widgets, materialization and lineage work on any step unchanged.
  - Equal calls give the same operator ids and share work. Different inputs or arguments give different ids, so two calls in one run never collide, and no binding is involved.
  - A **`CALL` operator** (new kind) stays as the grouping node: it names the function version and arguments, and takes the inlined output as its one input. Each inlined operator records its origin (function, version, call).
  - Runs never create operators: expansion happens in `add_call`, `build_pipeline`, when a scenario is saved and in `compare_scenarios`.
- **A scenario is a rewrite, not a run-time override.** It is a saved set of argument overrides and swapped inputs. Saving it rewrites, once, the graph under the operators it concerns (e.g. a dashboard's widgets) into scenario operators. Changed calls re-expand, and everything downstream re-derives with new inputs, while everything upstream keeps its ids and its cached results. The result is a stored map `baseline operator → scenario operator`.
  - Showing a scenario means reading the mapped operators. Runs stay exactly as they are, and so does the run model.
  - Comparison is composition: baseline and scenario operators side by side in one run, joined into a baseline/scenario/delta table.

**Paths:** `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`, `W/` = `services/widgets/src/`.

## Global Constraints

- Hexagonal layout and frozen-code rules from `docs/contracts.md`. Models, ports, `tables.py` and migrations change in an integration step.
  - `OperatorRow.kind` is a plain string, so a new kind needs no enum migration.
  - Adding `CALL` touches `OperatorKind` and `PARAMS`. `_Planner._plan` treats it as a pass-through of its one input (the inlined output); no expansion happens during planning.
  - `TransformParams` gains `parameters: JsonObject = {}` (bound values; part of the identity). An operator without parameters hashes exactly as before, so existing ids don't change.
  - Operators gain an optional `origin` (function id, version, call id; scenario id for scenario operators), stored in a column, not in the identity.
- Migrations: `0015_functions.py` (down `0014`) and `0016_scenarios.py` (down `0015`). Main has `0013_agent_turn_recovery` and `0014_freshness_before_watch` since 2026-11-14; the second to merge renumbers. Add them to the migration list in `contracts.md`.
- No SQL is built by string concatenation of user values. Parameters reach DuckDB only as bound parameters, and argument values are validated against the parameter's type and range before a run.
- No network in tests. Simulation tests use fixed seeds.
- Checks: `CI=1 mise exec -- moon run backend:lint backend:format backend:test frontend:lint frontend:typecheck frontend:test widgets:lint widgets:typecheck widgets:test`. Regenerate the client after REST changes.
- Commits in the repo's style, with the Claude co-author trailer.
- Coordinate with the platform agent before starting: it owns the platform. Tasks 1–6 are platform work and may be split between agents; tasks 7–9 are data work through MCP only.

## Review Focus

1. **Identity and caching:**
   - two calls with equal function version, arguments and inputs inline to the same operators;
   - changing one argument creates new operators only for the steps that read it and those downstream; upstream ids and results are reused;
   - a new function version never changes the operators of calls pinned to the old one;
   - existing operators (no parameters) keep their ids.
2. **Runs stay read-only:** no run, preview, query or widget read creates an operator.
3. **Safety:** parameters never reach SQL text; argument types and ranges are enforced; a function cannot call itself (directly or through another function).
4. **Marking:** every number that depends on a non-baseline argument or binding is marked simulated in widgets, reports and query results, and no simulated number appears without its scenario's name.
5. **Uncertainty:** simulation outputs carry intervals. A point estimate without its interval is refused by the scenario comparison widget.
6. **Existing data:** no existing operator, run, widget or report changes behaviour. The migration runs on the dev database.

---

## Part A: Functions

### Task 1: Function model, storage and versions

**Model** (`B/core/models/functions.py`):
- `FunctionParameter{name, type: integer|number|text|boolean|date, default, minimum?, maximum?, choices?, unit?, description}`.
- `FunctionInput{name, schema: Schema, description}`: the table contract, checked like an `INPUT`'s.
- `FunctionVersion{function_id, version: int, inputs, parameters, body: tuple[OperatorId, ...], output: OperatorId, output_schema, description, created_by, created_at}`.
- `Function{id, project_id, name, description, latest_version}`.
- Name rules as for widget inputs (`^[a-z][a-z0-9_]{0,63}$`).

**The body** is ordinary operators of the project, stored once. Its leaves are `INPUT` operators whose names are the function's input names (their defaults are the example data the author built it on), plus sources the function always reads (e.g. a reference table). Transforms in the body may reference parameters as `$name`. `output` is one operator of the body.

**Checks at creation:**
- every body `INPUT` is a declared function input and vice versa;
- every `$name` used in a body transform is a declared parameter;
- parameter defaults fit their types and ranges;
- the output schema derives;
- no call cycles.

**Versions are immutable.** Changing a function adds a version, and calls pin a version.

**Storage:** tables `functions` and `function_versions` (body and output stored as JSONB lists of operator ids, FK checked in the service) in migration 0015.

- [ ] **Step 1:** Failing tests:
  - create a function from an existing county pipeline (inputs: an indicator panel; parameter: `key`);
  - refuse an undeclared `$param`, a missing input, a self-call;
  - a second version leaves the first intact.
- [ ] **Step 2:** Implement the models, repository (SQL and memory), `FunctionService` (create, version, get, list) and migration. Run the checks, then commit.

### Task 2: Parameters in transforms

`TransformParams` gains `parameters: JsonObject = {}`: the values bound to the `$name`s its SQL reads. They are part of the operator's identity and are left out of the hash when empty, so existing ids are stable.

- **Function bodies:** a body transform is stored with its parameters' *defaults*, so the body runs as an ordinary pipeline on its example inputs. Inlining a call writes the call's values (task 3).
- **Deriving the schema:** with the operator's own parameter values bound.
- **Composing:** `fusion.compose` collects the parameter references of fused transforms and passes their values as DuckDB named parameters (`con.execute(sql, {"name": value})`). **Every path that composes SQL must carry them** (the platform agent's review): `query_operator`, which wraps the composed SQL in its own clauses; preview; schema derivation; and the alert check, which runs `condition_sql` over the rule's operator. Otherwise `$name` reaches DuckDB unbound. One helper returns `(sql, parameters)`, and every caller uses it.
- **Materializing:** nothing special. Different values are different operators, so their snapshots are different too.

- [ ] **Step 1:** Failing tests:
  - a transform with `$target_pct` derives with the default and runs with another value;
  - a text parameter with `'; DROP` stays a value;
  - two parameter values are two operators with two snapshots, and an operator without parameters keeps its old id.
- [ ] **Step 2:** Implement in `B/adapters/duckdb/` (execution) and `B/core/services/pipelines/fusion.py` (composition, keys). Commit.

### Task 3: The `call` operator

**Model:**
- `OperatorKind.CALL` with `CallParams{function_id, version, arguments: JsonObject}` (the effective arguments, defaults filled in). Its one input is the inlined output; its output schema is the version's.
- `origin` on every inlined operator: `{function_id, version, call: <call operator id>}`. It is metadata, not identity, so equal steps of different calls are one operator with several origins (stored as a list, or as the first origin; decide in implementation).

**Inlining** (`B/core/services/functions/inline.py`), at `add_call`, at a `build_pipeline` `call` step, when a scenario is saved and in `compare_scenarios`:
1. Check the arguments against the version's parameters (type, range, choices) and the inputs against its inputs (`check_fits`, `check_compatible`).
2. Walk the body from its leaves. A body `INPUT` becomes the call's input operator for that name. A source stays the same source operator. A transform becomes a transform with the same SQL, the inlined inputs and `parameters` = the call's values for the `$name`s it reads. A nested `CALL` inlines recursively; a cycle is refused.
3. Create each operator through the normal `PipelineService` path. Identity deduplicates, so an existing operator is reused.
4. Create the `CALL` grouping operator over the inlined output.

The whole call is one transaction: all or nothing.

**Runs:** unchanged. `CALL` plans as a pass-through of its input. Inlined steps are ordinary operators with ordinary entries `(run_id, operator_id)` in the same run, so the platform agent's blocker (call-scoped nodes outside `operators`) no longer arises.

**Scenario flag:** an operator whose origin is a scenario, or which reads one (transitively), is *simulated*, and `WidgetData` gains `simulated_by: [scenario names]`. The flag is computed from origins upstream, cached per operator, and drawn like `is_scenario` today. A call with non-default arguments is not simulated by itself: a function's defaults are just its defaults. Simulation is what a scenario changes.

**Tools and REST:**
- `add_call(project_id, session_id, function, version?, arguments, inputs)`. Every MCP tool in this plan takes `session_id`; the middleware refuses a call without it.
- A `build_pipeline` step `{"ref": "c", "call": {"function": "county_map", "version": 2, "arguments": {...}, "inputs": {"panel": "$p"}}}`, added to the `Step` union in `B/core/services/ports/batches.py` and `B/core/services/pipelines/batch.py`, next to `transform`.
- `create_function` / `update_function` (new version) / `list_functions` / `get_function` in MCP and REST.
- `get_lineage` returns the inlined steps as they are, with their origin, so clients can group them under their `CALL` node (collapsed by default, expandable).

- [ ] **Step 1:** Failing tests:
  - a call inlines into operators that read the given input and carry the argument values;
  - its steps have entries in the same run and can be queried with `query_operator`;
  - two calls of one function with different inputs in one run give two results;
  - equal calls create no new operators;
  - changing one argument re-creates only the steps that read it and those downstream;
  - a call of version 1 is unaffected by version 2;
  - a failing check creates nothing;
  - no run creates an operator.
- [ ] **Step 2:** Implement inlining, `CALL`, origins, the services, the tools and the lineage. Commit.

### Task 4: Functions in the frontend

- **Pipeline dialog:**
  - inlined steps grouped under their `call` node (function name, version and argument chips), collapsed by default; expanding shows the steps, each queryable like any operator;
  - the `kindLabels` and `Parameters` cases for `call`.
- **Functions page** in the project sidebar, under Pipelines (or a section of an existing page, decided with the platform agent): each function with its signature (inputs, parameters with defaults, ranges and units), its versions and where it is called.
- [ ] Tests, then implement. Commit.

## Part B: Scenario API

### Task 5: Scenarios as saved argument sets and bindings

**Model** (`B/core/models/scenarios.py`):
- `Scenario{id, project_id, name, description, arguments: {function_name: {param: value}}, call_arguments: {call_operator_id: {param: value}}, inputs: {operator_id: operator_id}, targets: [operator_id], revision, created_by, created_at}`.
- **Function-level arguments** apply to every call of that function; **call-level arguments** override one call; **`inputs`** swaps one operator for another (the static form of a binding, e.g. a "projected baseline" table instead of the measured one).
- `targets` are the operators the scenario is about, e.g. a dashboard's widget operators. Saving adds them all.

**The rewrite** (`B/core/services/scenarios/rewrite.py`), at create and update (each update is a new revision):
1. Walk upstream from each target.
2. A `CALL` whose arguments the scenario changes re-inlines with the new values (task 3). An operator in `inputs` is replaced. Any operator reading a replaced one re-derives with the new inputs (same SQL, same parameters, new identity). Everything else keeps its id.
3. New operators get `origin.scenario = <id, revision>`.
4. The result is stored as `scenario_operators(scenario_id, revision, baseline_operator_id, scenario_operator_id)`: one row per changed operator. Unchanged ones map to themselves implicitly.

**Reading a scenario:** `WidgetService.data(..., scenario_id)` and the dashboard run read the mapped operator for each widget input. The run model does not change: no `run.scenario_id`, no `bindings` needed for scenarios. `is_scenario` remains for the existing bindings.

**Comparison as composition:**
- **Compare operator.** `compare_scenarios(operator_id, scenarios: [names], keys, measures)` builds one transform over the baseline operator and the scenario operators of `operator_id`. It joins them on `keys` and outputs one row per key and scenario: `{scenario, measure, baseline, value, delta, delta_pct, lower, upper}`. It is an ordinary operator, so it runs in one run, lineages, caches and freezes in reports like anything else.

**MCP tools:**
- `create_scenario`, `update_scenario`, `list_scenarios`, `get_scenario`;
- `scenario_operator(scenario_id, operator_id)`, which returns the scenario's counterpart of an operator, for `query_operator`, `get_widget_data` or a new widget;
- `compare_scenarios`.

**Instructions:** a simulated number is presented only through a comparison or a widget marked simulated, always with the scenario's name and its assumptions.

**Alerts:** `check_alert_rule(rule_id, scenario_id?)` evaluates a rule on the scenario's counterpart of its measure without notifying anyone (spec §Alerts).

- [ ] **Step 1:** Failing tests:
  - a scenario rewrites only the operators downstream of its levers; upstream ids, and their snapshots, are reused;
  - the map is stable: saving the same scenario twice creates nothing new;
  - widget data with `scenario_id` reads the mapped operators and is marked simulated with the scenario's name;
  - the compare operator gives baseline, value and delta per key in one run;
  - a scenario that swaps an input and one that changes arguments both compare;
  - an alert checked on a scenario creates no alert.
- [ ] **Step 2:** Implement the models, migration 0016 (`scenarios`, `scenario_operators`; `operators.origin`, or put that in 0015), rewrite, service, tools and REST. Commit.

### Task 6: Scenarios in the frontend and widgets

- **Dashboard scenario bar:**
  - a selector "Baseline / <scenario>"; choosing one runs the dashboard on that scenario;
  - every widget shows the scenario marker, and the dashboard header names the scenario;
  - sliders for the scenario's parameters (from the function's types, ranges and units); moving one saves the scenario as a new revision and re-runs.
- **Comparison charts need no new widget type.** The `chart` type is full Vega-Lite 6.5: delta bars about zero with interval whiskers are a layer of a bar and an errorbar or rule. `custom` widgets with `data.inputs` cover anything Vega can't draw. Document the pattern in the `create_widget` description.
- **Pages pin their run.** A dashboard gets its run from `POST /dashboards/{id}/runs {time_range}`, and `useViewRun` restarts it when the live epoch changes. The scenario bar passes `scenario_id` to widget data (task 5), and keeps it across those restarts, so the page never drops back to the baseline on a refresh. Choosing a scenario saves the dashboard's widget operators as its `targets`, if they are missing.
- **Scenarios as session attachments:** `session_attachments.kind` is a free string (at most 16 characters), so `scenario` becomes an `AttachmentKind` without a migration, with a view in `F/components/attachments/attachment-views.tsx`.
- **Reports** already freeze their run and copies of their widgets. A report of a scenario copies widgets onto the scenario operators and stores `scenario_id` and the revision on the version; the sources section lists the scenario's arguments as "Assumptions".
- [ ] Tests, then implement. Commit.

## Part C: Simulations for the Nordic cancer care project

Built through MCP only, as functions and scenarios in the project. Every effect size is a source in ADA (web extract, checked against the paper) and every function parameter cites its source in its description.

### Task 7: Evidence and baseline sources

**Effect sizes** (a source per study, model-extracted and checked; most are found already):

| Lever | Effect size | Source |
| --- | --- | --- |
| Breast screening attendance | breast-cancer death RR 0.67 (0.49–0.90) for attenders in Finland; non-attender vs uninvited 1.56 (1.25–1.91), Finland | Br J Cancer 2016 (Finnish case–control); Sarkeala et al. 2008 |
| Breast screening invitation | RR 0.78 (0.75–0.82); attendance 0.67 (0.61–0.75), cohort meta-analysis | Dibden et al. 2020, Cancers |
| Treatment delay | HR per 4-week delay: surgery 1.06–1.08 (breast 1.08, 1.03–1.13; colectomy 1.06, 1.01–1.12), radical radiotherapy head and neck 1.09 (1.05–1.14), systemic 1.01–1.28 | Hanna et al., BMJ 2020 |
| Colorectal FIT screening | CRC mortality reduction about 9–12 % in a decade; to be pinned to one meta-analysis | to source |
| Smoking | population attributable fraction and potential impact fraction for Nordic smoking scenarios | Eur J Cancer 2018 (Prevent model, Nordic) |
| Education gradient | mortality HR 1.13–1.14 (low vs high education), stage IV OR 1.10–1.30 | Zai et al. 2025 (in ADA) |
| Care route | median symptom-to-treatment 127 vs 76 days | Kuitunen et al. (in ADA) |

**Baselines:**
- **Deaths by cause and county, per year:** Statistics Finland PxWeb `13u5` with the breast, colorectal, cervical, lung, pancreas and liver codes (the existing source has only some).
- **Incident cases by cancer** (national, and by county where published): the Cancer Registry's county incidence or NORDCAN's regions.
- **Screening attendance** by county (Sotkanet, in ADA) and by education (OECD, in ADA).
- **Survival:** NORDCAN (in ADA).
- **Lung time to treatment:** the Cancer Registry lung report (OCR source).

- [ ] Register the missing sources. Check every model-extracted effect against its paper (as done for Zai and OECD).

### Task 8: A projected baseline

A deviation is measured against where things are heading, not against today.

- **Projection function:** `project_baseline(series; horizon_year, method)`. It fits a log-linear trend per county or measure over the last N years and projects to the horizon (2030, 2035) with a prediction interval.
  - Methods: a linear or log-linear trend, or "flat" (last value).
  - Each method is documented in the function's description.
  - DuckDB `regr_slope`, `regr_intercept` and residual variance give the interval.
- **Strategy targets** (80 % screening, Nordic-level survival, −10 % mortality) are plotted against the projected baseline. That gives the **target gap** each scenario tries to close.
- [ ] Build the function. Show baseline, projection and target per goal; check the projections against held-out recent years (backtest the last 2 years).

### Task 9: Scenario functions, with uncertainty

Each is a function with typed parameters (defaults = the cited estimate, bounds = its CI). It outputs per county (or nationally) `{measure, baseline, scenario, delta, lower, upper}`. Uncertainty comes from Monte Carlo over the effect sizes: N draws, log-normal for ratios, seeded, materialized. The interval is the 2.5th–97.5th percentile of draws.

1. **`screening_uplift`**
   - **Inputs:** attendance by county, breast-cancer deaths by county (age 50–69 share).
   - **Parameters:** `target_attendance_pct` (default 80; also "low-education to high-education rate"), `rr_attend` (0.67, CI 0.49–0.90), `selection_dr` (1.56, 1.25–1.91), `lag_years`.
   - **Output:** breast-cancer deaths averted a year once the effect has matured, with the self-selection correction (the RR1/RR2 formulas of the cohort meta-analysis).
   - **Variants:** cervical and colorectal, with their own effect sizes.
2. **`delay_reduction`**
   - **Inputs:** incident cases by cancer, current median time to treatment.
   - **Parameters:** `weeks_saved` (e.g. down to Denmark's level; 127→76 days via the occupational route), `hr_per_4_weeks` per treatment (Hanna).
   - **Output:** relative change in mortality = HR^(−weeks_saved/4), applied to the cancer's 5-year deaths.
3. **`smoking_reduction`**
   - **Inputs:** daily smoking by county and education.
   - **Parameters:** target prevalence (e.g. the high-education rate), relative risks per cancer, latency.
   - **Output:** the potential impact fraction on smoking-related cancer incidence, and cases avoided by horizon year.
4. **`equity_gap`**
   - **Inputs:** deaths by education (Cancer Registry ch. 13 in ADA).
   - **Parameters:** the HR (Zai).
   - **Output:** deaths a year attributable to the education gradient (the excess if everyone had the high-education HR). It is the size of the prize, not a lever.
5. **`nordic_survival_gap`**
   - **Inputs:** NORDCAN survival, incident cases.
   - **Parameters:** target survival (the Nordic level, i.e. the strategy's +14 / +6 / +14 pp for lung, pancreas and liver).
   - **Output:** deaths within five years avoided a year.
6. **Other methods**, beside effect sizes, each marked with its assumptions:
   - **Standardisation:** what a county's survival or screening would be with another county's case mix or education profile. Uses the indicator panel; ecological, labelled as such.
   - **Benchmark substitution:** a Finnish county at the best county's level, or Finland at the Danish pathway share. This is the "achievable" scenario, not an effect estimate.
   - **Sensitivity (tornado):** for each scenario, how much each parameter across its CI moves the result. One compare run per parameter bound.

**Scenarios to save** (task 5):
- "Every county at 80 % screening";
- "Low-education women screen like high-education women";
- "Treatment within Danish pathway times";
- "Daily smoking at the high-education rate";
- "Strategy 2035 targets met".

**Dashboard:** a "Scenarios" dashboard with:
- the scenario bar;
- one comparison per scenario (delta per county, with intervals);
- a summary table (deaths or cases avoided a year, interval, the cited assumption);
- a tornado per scenario.

- [ ] Build the functions and scenarios through MCP. Check each function against a hand calculation for one county. Screenshot the dashboard in light and dark mode.

## After this: recommendations

An `AGENT` operator (model only today; the runner raises "cannot run yet"):
- it reads the comparison operators and writes Markdown recommendations *with placeholders* over its inputs;
- a text widget shows that Markdown;
- the judge (`text_widget`) checks every figure;
- it is always materialized, so reports freeze the recommendations.

Planned separately once scenarios exist.

## Open decisions (the user's)

1. **Monte Carlo draws:** proposal 2,000 draws with a fixed seed per scenario revision, so results are reproducible.
2. **Horizon years:** 2030 and 2035 (the strategy's).
3. **Where functions live in the UI:** their own sidebar page, or a section of the pipelines view.
4. **Who builds Parts A and B:** the platform agent, or me in a worktree, split by part.
