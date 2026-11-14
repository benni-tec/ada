# Wave 2, workstream I: alerts

What the alerts add to `docs/contracts.md`. Integration folds this in.

## Code

| Path | What it is |
| --- | --- |
| `core/services/alerts/formula.py` | The formula tree: parsing, type checks against the measure's schema, compilation to SQL, the text form |
| `core/services/alerts/service.py` | `Alerts`, the `AlertService` |
| `composition/providers/alerts.py` | Binds `AlertService` to `Alerts` (was a stand-in) |
| `entrypoints/http/routers/alerts.py` | REST routes |
| `entrypoints/mcp/tools/alerts.py` | MCP tools |
| `entrypoints/worker/tasks/alerts.py` | `check_alert_rule`, `check_due_alert_rules` |
| `tests/test_alerts_*.py`, `tests/alerts_support.py` | Tests and their shared setup |
| frontend `src/lib/api/alerts.ts` | Types, requests, query keys and query options |
| frontend `src/components/alerts/**` | Feed, rules, rule editor, formula builder, `AlertBadges`, project section |
| frontend `src/routes/projects/$projectId/alerts/index.tsx` | The alerts page |

## The formula

`AlertRule.formula` is a JSON tree. Every node has an `id`, unique in the tree (1 to 64
letters, digits, `-` or `_`), and a `kind`. Composite nodes list their operands in `args`,
in order. Ids exist from the start so that an interface can address a sub-expression: a
later graph builder that lets rules share sub-expressions changes the interface only.

| `kind` | Fields | Operands | Type |
| --- | --- | --- | --- |
| `column` | `column` | | The column's: integer and number are `number`; text, boolean, date, timestamp as they are; JSON columns cannot be used |
| `constant` | `value`, optional `type` | | A JSON number is `number`, a string `text`, true or false `boolean`; `type: "date"` or `"timestamp"` takes an ISO 8601 string |
| `arithmetic` | `op`: `+ - * /` | 2 numbers | number. Dividing by zero is NULL |
| `compare` | `op`: `< <= > >= = !=` | 2 of the same type | boolean. Booleans take only `=` and `!=` |
| `and`, `or` | | 2 or more booleans | boolean |
| `not` | | 1 boolean | boolean |
| `previous` | `periods` (default 1) | 1 of any type | The operand's type: its value that many periods earlier |
| `change` | `periods` (default 1) | 1 number | number: the operand minus its value that many periods earlier |
| `rolling_mean` | `periods` (default 1) | 1 number | number: the mean over the last `periods` periods, this one included; NULL until that many periods with a value exist |

- The root must be boolean.
- `periods` is a whole number from 1 to 1000. A tree has at most 200 nodes and nests at
  most 32 levels.
- Unknown fields on a node are an error, so a typo is not silently ignored.
- **Time functions** need the measure's time role (`Schema.roles.time`). A period is a
  row; the previous period is the previous row by the time role's `start` within the same
  key. They nest (`change(change(value))`).
- **Which rows are evaluated.** With a time role, each key's latest period (by `start`);
  earlier periods only feed the time functions. Without a time role, every row. A key
  alerts when one of its evaluated rows does. Key columns plus the time start must
  identify a row: if they do not, "previous" picks one of the tied rows.
- **NULL never alerts.** A condition that is NULL counts as false, so missing history (a
  change with no earlier period) and division by zero never alert.
- **Suppressed values never alert.** For a measure role with a `suppressed` flag, the
  value, lower and upper columns are NULL where the flag is true, so they feed no time
  function and no comparison; and a row where a measure the formula reads is suppressed
  never alerts, even if the condition does not depend on the value (e.g. `or`).
- Measure columns may not start with `__ada_`; the compiled query uses that prefix.
- **Errors** are `Invalid` with the message `Formula node '<id>': <what is wrong>` whenever
  one node is at fault, e.g. `Formula node 'v1': 'nope' is not a column of the measure
  (region, start, end, value)`. REST answers 422 with it as `detail`; MCP returns it as
  the tool error. The frontend reads the id from that prefix and marks the node.

Example, "below 80, or down 5 points on the previous period":

```json
{"id": "root", "kind": "or", "args": [
  {"id": "low", "kind": "compare", "op": "<", "args": [
    {"id": "v1", "kind": "column", "column": "value"},
    {"id": "c80", "kind": "constant", "value": 80}]},
  {"id": "drop", "kind": "compare", "op": "<=", "args": [
    {"id": "chg", "kind": "change", "periods": 1, "args": [
      {"id": "v2", "kind": "column", "column": "value"}]},
    {"id": "c5", "kind": "constant", "value": -5}]}]}
```

Its text form, the same on the server (`describe`) and in the frontend (`describe` in
`components/alerts/formula.ts`): `value < 80 or change(value, 1 period) <= -5`. Only the
parentheses the meaning needs are written, except that the operand of `not` is always
parenthesised unless it is a single value.

Other examples: `{"kind": "compare", "op": ">", "args": [{"kind": "rolling_mean",
"periods": 3, "args": [col]}, const]}` (the three-period mean is above a value);
`{"kind": "compare", "op": "=", "args": [{"kind": "column", "column": "region"},
{"kind": "constant", "value": "Helsinki"}]}` (text); `{"kind": "constant", "value":
"2024-01-01", "type": "date"}` (a date to compare with a date column). Ids omitted here
for brevity; they are required.

### Compilation to SQL

`compile_rule(formula, schema, key_columns)` checks the key columns and the formula against
the measure's output schema and returns one SELECT over `input_0` (the measure), built in
layers because SQL windows cannot nest:

1. `__ada_l0`: the measure with suppressed values set to NULL (`SELECT * REPLACE (...)`).
2. `__ada_l1` … : one layer per time function, innermost first, adding a window column
   `__ada_t<n>` partitioned by the key columns and ordered by the time start.
   `previous` is `lag(x, n)`, `change` is `x - lag(x, n)`, `rolling_mean` is
   `avg(x)` over `ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW` when `count(x)` over the same
   frame is `n`, else NULL.
3. `__ada_eval`: the condition as `__ada_alerting`, and, with a time role, each row's
   recency within its key as `__ada_recency`.
4. The alerting rows: `__ada_alerting IS TRUE`, the key's latest period, and no read
   measure suppressed; the helper columns are excluded, so the output has exactly the
   measure's columns, ordered by the key columns and the time start.

Numbers are compared as `DOUBLE`, text constants are SQL string literals with quotes
doubled, and column names are quoted identifiers, so nothing in a formula is pasted into
SQL as code. The example above compiles to:

```sql
WITH __ada_l0 AS (
SELECT * REPLACE (CASE WHEN "suppressed" THEN NULL ELSE "value" END AS "value") FROM input_0
),
__ada_l1 AS (
SELECT *, ("value" - lag("value", 1) OVER (PARTITION BY "region" ORDER BY "start")) AS "__ada_t0" FROM __ada_l0
),
__ada_eval AS (
SELECT *, ((("value" < CAST(80 AS DOUBLE)) OR ("__ada_t0" <= CAST(-5 AS DOUBLE)))) AS "__ada_alerting", row_number() OVER (PARTITION BY "region" ORDER BY "start" DESC) AS "__ada_recency" FROM __ada_l1
)
SELECT * EXCLUDE ("__ada_t0", "__ada_alerting", "__ada_recency")
FROM __ada_eval
WHERE "__ada_alerting" IS TRUE AND "__ada_recency" = 1 AND "suppressed" IS NOT TRUE
ORDER BY "region", "start"
```

## Traceability: the alerting operator

The compiled SQL becomes a pass-through transform over the measure operator, added with
`PipelineService.add_transform(project, sql, [measure], Actor(system, "ada"),
roles=measure's roles)`. Its output in a check's run is the set of alerting rows.

- **Why an operator, not a query on the side.** The condition becomes part of the
  lineage like any SQL step: the alerting rows have an address (run id plus operator id),
  are answered by the same fused query and snapshot reuse as everything else, and the run
  fixes which snapshots they rest on. Describing it when the rule is created is the last
  check that the SQL binds. The operator id is the identity of the SQL and the measure, so
  every check of an unchanged rule reuses the same operator, and a changed formula is a
  new operator while the old one stays for the alerts it raised.
- It is added when a rule is created or its formula changes, and again (a lookup) by
  every check.
- An alert's `since_run_id` and `last_run_id` name the runs; the alerting rows are
  `GET /api/runs/{last_run_id}/operators/{alerting operator}/rows`. The alerting
  operator's id is not stored on the rule or the alert (the models are frozen); it is
  `operator_identity(project, "transform", {"sql": compile_rule(...).sql}, [measure])`.
  The frontend shows the measure's rows for the alert's key in `last_run_id` instead,
  which includes the alerting row and the history its time functions read.

## AlertService

Bound per request like every service; all checks run as `Actor(kind="system", name="ada")`.

- **`create_rule`** reads the dashboard (`NotFound` otherwise) and takes its project.
  `Invalid` when: the name is empty; an interval or maximum age is not positive; the
  measure operator does not exist, is in another project, is not a table, or has no known
  columns (a source registered without a schema: build the rule on a transform over it);
  a key column is missing, repeated or JSON; the formula does not check; the compiled SQL
  does not bind; the alert pipeline does not exist, is in another project, does not have
  exactly one input slot upstream, or that slot's declared columns are not among the
  measure's (an integer fits a number).
- **`update_rule`** changes name, formula, severity, interval and enabled, checks the
  result like a new rule, and is revision-checked. `last_checked_at` is never written by
  it.
- **`check(rule_id)`**, in one unit of work:
  1. Reads the rule and its measure, and adds (finds) the alerting operator.
  2. **Maximum data age.** For each source operator upstream of the measure, the data was
     last known current at the newest of its snapshots' `fetched_at` and, when the last
     refresh succeeded, the source's `last_checked_at` (a refetch with identical content
     writes no snapshot but confirms the data). Older than `max_data_age_seconds`, or
     never fetched: `SourceService.refresh(id, force=True)`. A failed forced refresh is
     logged; the check goes on with the last good snapshot, as every run does, and the
     failure is recorded on the source and announced as `source.refresh_failed`.
  3. Starts a run and reads the alerting operator's output in it (at most 10 000 rows; more
     fails the check with `Invalid`, since resolving the rest would be guesswork). The run
     refreshes sources by their own policies as usual.
  4. Per distinct key (the key columns' values, dates as ISO strings): a key without a
     firing alert gets a new `firing` alert (`since_run_id = last_run_id = run`,
     `started_at = now`); a key with one keeps it and gets `last_run_id = run`; a firing
     alert of the rule whose key no longer alerts is `resolved` (`resolved_at = now`,
     `last_run_id` stays the last run that showed the condition). A key that alerts
     again later gets a new alert.
  5. Publishes `alert.firing` / `alert.resolved` for every alert that started or resolved.
  6. If the rule has an alert pipeline and a new alert fired, runs it (below).
  7. `record_check(rule, at)` with the time the check **started**, so data that arrives
     during the check makes a rule without interval due again.

  Everything that can fail (refresh, the run, the read) happens before any alert is
  written, so a failed check leaves the alerts as they were. Returns the alerts that
  started or resolved.
- **Alert pipeline.** Runs in a run of its own, started with the binding
  `{<its input slot's name>: <alerting operator>}`, with every snapshot of the check run
  fixed into it first (`RunRepository.fix_snapshot`), so it sees exactly the check's data.
  A separate run because a binding marks a run as a scenario, and the check run must not
  be one. Its failure is logged and does not undo the alerts; the run says `run.failed`.
  The alert pipeline's run id is not recorded on the alert (no field); find it by the
  `run.finished` event or the project's runs.
- **`due()`**: enabled rules that were never checked; with `check_interval_seconds`, those
  whose interval has passed since `last_checked_at`; without one, those whose measure's
  data changed since `last_checked_at`, detected cheaply: one upstream walk
  (`OperatorRepository.upstream`) and one snapshot listing per source operator, true when
  any snapshot's `fetched_at` is later than the last check. A refresh writes a snapshot
  only when the content changed, so this reads no data and fetches nothing. Listing all
  snapshots (not only the current one) keeps working when snapshots are stored per
  period (workstream J).
- **`alerts(project, state)`**: newest first, as the repository returns them.

## Worker tasks

| Task | When | Does |
| --- | --- | --- |
| `ada.entrypoints.worker.tasks.alerts:check_alert_rule(rule_id: str)` | Queued by `check_due_alert_rules` (and by anyone through `TaskDispatcher.check_alert_rule`) | Reads the rule; skips it when it was disabled after being queued; `AlertService.check`. A failure is logged and the task ends normally (the rule stays due and is queued again on the next tick) |
| `ada.entrypoints.worker.tasks.alerts:check_due_alert_rules()` | Every minute (scheduler) | Queues `check_alert_rule` for each rule `AlertService.due()` returns; a failure to queue one is logged and the others are still queued |

## Live events

| Event | Payload | When |
| --- | --- | --- |
| `alert.firing` | `alert_id`, `rule_id` | A check opened an alert |
| `alert.resolved` | `alert_id`, `rule_id` | A check resolved one |

Published through the transactional publisher: after the check's unit of work commits,
never after a rollback. A check also causes the usual `run.started` / `run.finished`
(or `run.failed`) and, when it refreshes, `source.refreshed` / `source.refresh_failed`.

## REST

| Method and path | Body | Answers |
| --- | --- | --- |
| `GET /dashboards/{id}/alert-rules` | | `AlertRule[]`, oldest first; 404 for an unknown dashboard |
| `POST /dashboards/{id}/alert-rules` | `name, operator_id, formula, key_columns`, optional `severity` (default `warning`), `check_interval_seconds, max_data_age_seconds, alert_pipeline_id` | 201 `AlertRule`; 422 with the formula error |
| `GET /alert-rules/{id}` | | `AlertRule` |
| `PATCH /alert-rules/{id}` | `expected_revision`, optional `name, formula, severity, check_interval_seconds, enabled` | `AlertRule`; 409 with both revisions |
| `POST /alert-rules/{id}/check` | | `CheckResult {rule, changed: Alert[], firing: Alert[]}`. Runs the check in the request: a person who asks wants the answer; scheduled checks go through the worker |
| `GET /projects/{id}/alerts?state=firing\|resolved` | | `AlertView[] {alert, rule}`: firing first, newest first within a state |
| `GET /dashboards/{id}/alerts?state=` | | `AlertView[]` of the dashboard's rules, same order (for the badges) |
| `GET /projects/{id}/alert-rules` | | `DashboardRules[] {dashboard, rules}`: every dashboard of the project (oldest first) with its rules. Uses `DashboardService.list` (workstream G); a stand-in until G is merged |

## MCP tools

| Tool | Does |
| --- | --- |
| `create_alert_rule(dashboard_id, name, operator_id, formula, key_columns, severity?, check_interval_seconds?, max_data_age_seconds?, alert_pipeline_id?)` | Creates a rule. Its description carries the whole formula format with an example |
| `list_alert_rules(dashboard_id)` | A dashboard's rules |
| `get_alert_rule(rule_id)` | One rule with its revision |
| `update_alert_rule(rule_id, expected_revision, name?, formula?, severity?, check_interval_seconds?, enabled?)` | Changes a rule |
| `refresh_alerts(rule_id)` | Checks a rule now; returns `{rule, changed, firing}` |
| `list_alerts(project_id, state?)` | The feed: `{alert, rule_name, severity, dashboard_id, url}` entries, firing first; `url` is `/projects/{id}/alerts` |

The check tool is `refresh_alerts`, not `check_alert_rule`: `tests/test_api_mcp.py`
allows only the wave 1 verbs (`list create register update refresh add get preview
system`). Integration may add `check` to that list and rename it.

## Frontend

- **Route** `/projects/$projectId/alerts`: the feed (filter All / Firing / Resolved; each
  alert with severity, key, rule, since when or when resolved, and "Show the data", which
  reads the rule's measure in the alert's `last_run_id` and shows the key's rows), and
  "Rules by dashboard": each dashboard's rules with their condition in words, interval,
  last check, "Check now" and "Edit", and "New rule".
- **Rule editor** (`components/alerts/rule-editor.tsx`): name; the measure, picked from
  the operators behind the project's widgets or typed as an operator id (create only); key
  columns from the measure's columns (create only); severity; interval in minutes;
  maximum data age (create only); enabled (edit only); the formula builder.
- **Formula builder** (`components/alerts/formula-builder.tsx`): one row per node with its
  kind, settings (column picked from the measure's schema, constant with type, operator,
  periods) and actions: move up/down among its siblings, nest in a new node, add a
  condition to and/or, unwrap (replace by its first operand), remove (operands of and/or).
  Time functions are offered only when the measure has a time role. Below it the condition
  in words. A server error is shown and its node gets `aria-invalid` and a red border.
- **`AlertBadges({ dashboardId })`** (`components/alerts/alert-badges.tsx`): counts of the
  dashboard's firing alerts per severity, a link to the feed; "No alerts firing" when none;
  nothing while loading. Integration places it on G's dashboard page.
- **Project page**: an "Alerts" section with the firing counts and a link to the feed.
- **Query keys** (`alertKeys` in `lib/api/alerts.ts`): `['alerts', …]` for the feed and
  the badges, `['alert-rules', …]` for rules. `alert.firing` and `alert.resolved`
  invalidate both prefixes (`lib/events.ts`): the payload does not say which dashboard.

## Problems with the frozen contracts

- **`AlertService.update_rule` cannot change everything a rule has.** It takes no
  `key_columns`, `max_data_age_seconds` or `alert_pipeline_id`, and `None` means
  "unchanged", so an interval cannot be removed (back to "when the data changes") and a
  maximum age cannot be set after creation. Suggested: add those parameters, with an
  explicit way to clear (e.g. a sentinel, or `0` meaning none).
- **The alerting operator is not recorded.** Neither `AlertRule` nor `Alert` holds the
  alerting operator's id, so a client cannot open the exact alerting rows without
  compiling the formula. Suggested: `Alert.operator_id` (the operator whose output in
  `last_run_id` shows the alert), or `AlertRule.alerting_operator_id`.
- **An alert pipeline run is a scenario.** `Run.is_scenario` is any binding, so the alert
  pipeline's run, whose only binding is the alerting rows, is flagged as a scenario and
  its widgets would say "simulated". Suggested: distinguish bindings that simulate from
  bindings that feed an alert pipeline, or let a run start with snapshots fixed and the
  pipeline's input default to the alerting operator.
- **No record of an alert pipeline's run.** `Alert` has no field for it; the spec wants
  its summary attached to the alert event.
- **`AlertRepository` has no "firing alerts of a rule".** The check lists the project's
  firing alerts and filters by rule; fine for now, a query per rule would scale better.

## Problems found in other code

- **A refresh that finds changed content fails on PostgreSQL.**
  `DataSources._fetch` (`core/services/sources/service.py`) adds the new snapshot before
  superseding the current one; the partial unique index `uq_snapshots_current`
  (`operator_id, parameters_key WHERE superseded_at IS NULL`) rejects the insert, so the
  second successful fetch of changed data raises `IntegrityError`. The memory
  repositories do not enforce it, which is why the wave 1 tests pass. Fix: supersede the
  current snapshot first, then add the new one. `tests/test_alerts_db.py` works around it
  by changing the formula instead of the data.

## Known limits

- Two checks of the same rule at once (a scheduled one and "Check now") can both open an
  alert for the same key; the unique index `uq_alerts_firing` rejects the second, and that
  check fails. The rule is due again on the next tick.
- A check slower than a minute is queued again by the next tick (its `last_checked_at`
  is written at the end), like slow source refreshes.
- A disabled rule keeps its firing alerts until it is enabled and checked again.
- After an edit, alerts follow the new formula from the next check; "Check now" checks at
  once.
- `GET /projects/{id}/alert-rules`, and with it the rules on the alerts page, depends on
  `DashboardService.list`, a stand-in until workstream G is merged: it answers 500 until
  then (the tests bind a small stand-in over the dashboard repository). Everything else
  reads dashboards through `DashboardRepository`, which works already.
