# Contracts

What the workstreams of `docs/plan.md` agree on. These are fixed for a wave: if one
turns out wrong, report it instead of changing it, so everyone changes together.

The spec (`docs/spec.md`) says what the system does and why. This file says where things
live and how the pieces talk. It describes the code as integrated after wave 3.

## Frozen code

Do not edit these during a wave; build against them. The integration after a wave may
change them, minimally and backward compatibly, when a workstream asked for it.

| Path | What it is |
| --- | --- |
| `ada/core/models/**` | The domain models |
| `ada/core/ports/**` | Outbound ports: repositories, analysis store, source readers, source locks and the check log, events, tasks, transactions, clock |
| `ada/core/services/ports/**` | Inbound ports: one service per use-case group |
| `ada/adapters/db/tables.py`, `ada/adapters/db/migrations/**` | Every table. Migrations: `0001` the foundation, `0002` after wave 2, `0003` the agent (wave 3), `0004` alert conditions kept as SQL instead of operators (and the old condition operators removed) |
| `ada/discovery.py`, `ada/composition/__init__.py`, `ada/composition/unbuilt.py` | How features register themselves |
| `tach.toml` | Module boundaries. They are per package, so new files in an existing package need no change |

What the integration after wave 2 changed in them:

| Where | Change |
| --- | --- |
| `core/models/time.py`, `core/models/schema.py` | `Grain` (`year`, `quarter`, `month`); `TimeRole.grain` (J) |
| `core/models/base.py` | `Unchanged`, `UNCHANGED` and `Change[T]`: an update argument that was not given, where None means "clear" |
| `core/models/reports.py` | `ReportSource`: one entry of a report version's sources list |
| `core/models/alerts.py`, migrations `0002`, `0004` | `Alert.condition_sql` (`0004`, in place of `0002`'s `condition_operator_id`), `Alert.pipeline_run_id`, both nullable |
| `core/services/ports/sources.py` | `SourceService.refresh_range(id, time_range)`, with a default body returning None (J) |
| `core/services/ports/reports.py` | `ReportService.sources(version_id)` |
| `core/services/ports/alerts.py` | `AlertService.update_rule` also takes `key_columns`, `max_data_age_seconds`, `alert_pipeline_id`; the three fields that may be empty take `Change[...]` |
| `core/ports/sources.py` | `SourceLocks`: one unit of work fetches a source at a time |
| `core/services/ports/runs.py` | `RunService.snapshot(id)`: a snapshot by id, for the pipeline view (after wave 2) |

What wave 3 (the agent) added to them:

| Where | Change |
| --- | --- |
| `core/models/agents.py` | `ModelInfo`, `ModelList`, `AgentTurn`, `TurnStatus`, the four parts, `PostedMessage`, `TurnRequest`, `HistoryMessage`, `ToolSpec` |
| `core/models/pipelines.py` | `Pipeline`, `PipelineSource`: one entry of the pipelines list |
| `core/models/sessions.py` | `Context` (`PipelineContext`, `DashboardContext`, `WidgetContext`), `SessionEntry.context`, `EntryKind.AGENT_TURN` |
| `core/models/widgets.py` | `Widget.copied_from` |
| `core/models/events.py` | `agent.turn_started`, `agent.turn_part`, `agent.turn_finished` |
| `core/ports/agents.py` | `LanguageModels` (the models file), `AgentRuntime` (runs a model with tools), `AgentTools` and `AgentToolbox` (the tools of a turn), `TurnSink` (where a running turn reports parts), `TurnProgress` (a running turn's writes, each committed at once), `AgentFailed`, `ToolCallFailed` |
| `core/ports/repositories.py`, `core/ports/tasks.py` | `AgentTurnRepository`; `TaskDispatcher.run_turn` |
| `core/services/ports/agents.py` | `AgentTurnService`: `models`, `post_message`, `turns`, `get`, `cancel`, `run` |
| `core/services/ports/sessions.py`, `pipelines.py` | `SessionService.add_message(..., context)`, `record_agent_turn`, `dashboard_agent_session`; `PipelineService.pipelines` |
| Migration `0003` | `session_entries.context` (JSONB, default `[]`), `widgets.copied_from` (to widgets, `SET NULL`), the table `agent_turns` (with `cancel_requested`) |
| `tach.toml` | Inbound ports may name outbound ports (`AgentTurnService.run` takes the toolbox its caller provides); the worker may import `ada.entrypoints.mcp` (the agent's tools are the MCP tools, served in process) |

## Adding a feature without touching shared files

Four packages are scanned at startup. A feature adds a module; no list is edited.

| To add | Create a module in | It must expose |
| --- | --- | --- |
| REST routes | `ada/entrypoints/http/routers/` | `router = APIRouter(route_class=DishkaRoute, tags=[...])` |
| MCP tools | `ada/entrypoints/mcp/tools/` | `register(mcp, inject)`, defining tools with `@mcp.tool` and `@inject` |
| Worker tasks | `ada/entrypoints/worker/tasks/` | functions decorated with `@task(...)` from `ada.entrypoints.worker.registry` |
| Bindings | `ada/composition/providers/` | `provider`, a dishka `Provider` instance |

### Who binds what

Every port is bound in exactly one provider module, and since wave 2 every one of them to
a real implementation. A port added by a later wave is bound to the stand-in
(`unbuilt(Port)`) until it is built: the application starts, and using the port raises
`NotImplementedError` naming it. `tests/test_composition.py` checks that no port is left
on the stand-in.

| Provider module | Ports |
| --- | --- |
| `infrastructure.py` | Settings, database engine and request session, `AfterCommit` (`PendingWork`), Valkey client, `Clock` |
| `system.py` | `Database`, `TaskQueue`, `SystemStatusService` |
| `repositories.py` | All thirteen repositories (SQLAlchemy, on the request's session); `SourceLocks` (advisory locks on the request's session); `SourceCheckLog` and `TurnProgress` (own connection, a short transaction per write) |
| `analysis.py` | `AnalysisStore` (Parquet and DuckDB), `PipelineService`, `RunService` |
| `sources.py` | `SourceReaders` (HTTP: URL and request sources), `SourceService` |
| `workspace.py` | `ProjectService`, `SessionService`, `WidgetService` |
| `background.py` | `EventBroadcaster` (Valkey pub/sub), `EventPublisher` (transactional, per request), `EventStream` (Valkey), `TaskDispatcher` (taskiq on Valkey) |
| `dashboards.py` | `DashboardService` (`Dashboards`) |
| `reports.py` | `ReportService` (`Reports`), `TemplateService` (`Templates`) |
| `alerts.py` | `AlertService` (`Alerts`) |
| `agents.py` | `LanguageModels` (the models file, read once per process), `AgentRuntime` (`PydanticAiRuntime`), `AgentTurnService` (`AgentTurns`). The toolbox is not bound: whoever runs a turn passes it |

Services are bound at `Scope.REQUEST`; whatever holds a connection or shared state at
`Scope.APP`. The in-memory repositories, event bus and task dispatcher in
`ada/adapters/memory` are not bound by default; tests bind them (below).

## Units of work and transactions

One HTTP request, one MCP tool call and one worker task are each one unit of work: one
dishka `REQUEST` scope, one database session, one transaction. It commits when the unit
ends normally and rolls back when it raises.

- **REST.** The core's errors are turned into responses by `DomainErrorMiddleware`
  (`entrypoints/http/errors.py`), which sits outside dishka's middleware, so the error
  passes through the scope and rolls it back first. FastAPI exception handlers would
  answer from inside the scope and commit a failing request's writes; do not add any for
  the core's errors.
- **MCP.** `make_inject` (`entrypoints/mcp/injection.py`) opens the scope per call and
  turns the core's errors into `ToolError`s outside it.
- **Worker.** `ContainerMiddleware` (`entrypoints/worker/factory.py`) ends a failed
  task's scope with its exception; dishka's own taskiq middleware ended it as a success.
- **After the commit.** `AfterCommit.add(action)` runs an action once the unit's
  transaction has committed, never after a rollback. A failing action is logged, not
  raised: the commit cannot be undone. The REST and MCP source update paths use it to
  queue the forced refresh; posting a message uses it to queue the agent's turn.
- **Agent turns.** A turn is not one unit of work. Each tool call the agent makes is one,
  as over MCP; the turn's own writes go through `TurnProgress`, each in a short
  transaction of its own (see The agent).

## Behaviour every implementation of a port must share

The in-memory repositories (`ada/adapters/memory/repositories.py`) are the reference, and
`tests/test_memory_repositories.py` states the expectations. The database repositories
pass the same ones (`tests/test_db_repositories.py`).

- **Not found.** `get` raises `NotFound(kind, id)`.
- **Revisions.** Mutable records start at revision 1. `update(model, expected_revision)`
  raises `Conflict` and changes nothing when the stored revision differs; otherwise it
  stores the record and returns it with the revision increased by one.
- **Writes that are not edits.** `DataSourceRepository.record_check` and
  `AlertRuleRepository.record_check` write only what a refresh or a check found
  (`last_checked_at` and, for sources, `last_probe_token` and `last_error`) with a plain
  UPDATE that leaves the revision alone, so a refresh or check never makes a concurrent
  edit conflict, and `update` never writes those columns, so an edit never puts back an
  old outcome. An agent turn has no revision: its writes are plain UPDATEs of their own
  columns (see The agent).
- **Immutable records.** Operators, snapshots, runs, dashboard versions and report
  versions are only ever added. A source operator keeps the output schema the source was
  registered with, even after the source's declared schema is edited.
- **Operator ids.** `operator_identity(project_id, kind, params, inputs)` is the id.
  Adding an operator that exists returns the stored one.
- **Runs fix snapshots once.** `fix_snapshot` keeps the first snapshot recorded for an
  operator.
- **Events go out after the commit.** Services publish through the request-scoped
  `EventPublisher`, which hands each event to `AfterCommit`; the APP-scoped
  `EventBroadcaster` (Valkey) delivers it once the unit has committed, and it is dropped on
  a rollback. A client that fetches on an event finds what it names; failed work announces
  nothing. `publish` never raises. The agent's turns are the exception (see Live events).
- **External failures are `Unavailable`.** An external dependency that could not be
  reached or answered with an error (a data source, the task queue) raises
  `Unavailable` (`core/models/errors.py`): nothing is wrong with the request and retrying
  later may work. The HTTP readers' `SourceUnavailable` is one; the Valkey dispatcher
  turns taskiq's `SendTaskError` into one.
- **Unchanged versus cleared.** Where an update may empty a field, the service port takes
  `Change[T]`: `UNCHANGED` (the default) keeps the field and `None` clears it. For fields
  that cannot be empty, `None` keeps them, as before.

## Sources

Shared by the sources, the pipelines, the worker and the alerts:

- **The source operator is made by `register`.** `SourceService.register` stores the data
  source and its one source operator, whose identity is fixed:
  `operator_identity(project_id, SOURCE, {"data_source_id": "<id>"}, ())`
  (`source_operator_id` in `core/services/sources/service.py`). `add_source_operator`
  computes the same id, so it finds that operator.
- **Snapshot keys.** Every snapshot of a source belongs to its source operator. Its
  `parameters_key` says what it holds: `""` the whole source (wave 1),
  `period:<start>/<end>` one period of a source with pushdown (`Snapshot.period` set), and
  `range:<digest>` the union of the periods a run asked for, keyed by the periods' keys and
  content hashes. At most one snapshot per operator and key is current
  (`uq_snapshots_current`); a new one supersedes the old one first, then is added.
- **A whole-source refresh respects freshness.** `refresh(id)` does nothing while the
  current snapshot is fresh by the source's policy; with a probe policy it fetches only
  when the probe token changed. `refresh(id, force=True)` skips both. A refresh writes a
  snapshot only when the content hash changed. A forced refresh, and one that sees a new
  probe token, also retires every stored period and union.
- **One fetch of a source at a time.** A refresh that would probe, fetch or put a union
  together first takes `SourceLocks.hold(source)` (on PostgreSQL a transaction-level
  advisory lock, held until the unit of work ends) and then reads again what it decided
  on, since the unit that held the lock may have stored it meanwhile. Runs on fresh data
  never wait. Without it, two widgets reading the same run would both store a missing
  period, and the second insert would fail.
- **A failed refresh stays recorded.** The failure (`last_error`) is written through
  `SourceCheckLog`, in its own short transaction, before the error is raised on; the
  caller may roll back. A success is recorded in the caller's transaction, with the
  snapshot it wrote. A failed refresh keeps the last good snapshot current, and widgets on
  it show `is_stale`.
- **Edits refetch.** A REST or MCP update that changes a source's `address` or `options`
  queues `refresh_source(id, force=True)` after the commit.
- **Registration checks.** `register` and `update` check the declared schema's roles
  (below), that its column names are unique, and the `pushdown` and `period` options.

### Periods and pushdown

A period is an `Interval`, both ends inclusive. A time role names the columns of a
period's first and last day (`date` or `timestamp`); `grain` says what every period spans,
and windows such as 2020–2024 have none. **A row is in a time range when its period and
the range share at least one day**; periods are atomic, and a row without a period is in
no bounded range.

`ada.core.services.schema.time` reads a source's own way of writing a period
(`parse_period`: `2024`, `"2020-2024"`, `"2024Q1"`, `"2024M03"`, `"2024-03"`,
`"2024-03-15"`), splits a range into the periods of a grain, writes a period for a request
(`label`) and names its snapshot (`period_key`).

Options in `DataSource.options`, for JSON and CSV:

| Option | Meaning |
| --- | --- |
| `period: {column, start?, end?, grain?}` | Adds each row's period as two ISO date columns (`period_start`, `period_end` by default), read from `column`, after `fields`. Declare them as `date` and as the time role |
| `fields: {name: {path, type}}` | Also takes the type `json`: a nested value kept as its JSON text |
| `pushdown: {param \| body, format?}` | How the source takes periods: `param`, a query parameter repeated per period (Sotkanet's `years`), or `body`, a dot path into a request source's JSON body whose value becomes the list of periods; `format` writes a period with `{year}`, `{quarter}`, `{month}`. Needs a declared time role with a grain; exactly one of `param` and `body` |

What a run does with its time range, for each source operator (`Runs._Planner._source`):

1. With pushdown and a range that has a start, `SourceService.refresh_range(source,
   range)`: the range is split into the grain's periods (an open end runs to the period
   containing today); the missing and stale ones are fetched **in one request** and split
   by period, each stored as a period snapshot (a period with no rows as an empty table,
   so it counts as fetched); the result is the union snapshot, which the run fixes.
2. Otherwise (`None`), wave 1: `refresh(source)` and the whole snapshot.
3. In both cases, when the source operator has a time role and the range is bounded, the
   run filters its rows by the overlap rule (`PeriodFilterNode` in `pipelines/fusion.py`).

The range enters a node's content identity only through the period filter or the period
snapshots, so materialized transforms are keyed per range exactly where their input
changed. A run without a range (widgets outside a dashboard, `preview_operator`, alert
checks) reads the whole source as in wave 1.

Freshness by period: the newest periods (from the start of the latest stored period with
rows onwards) are stale after `latest_period_ttl_seconds` when set; otherwise `ttl` by
`ttl_seconds`, `probe` when the probe's token changed (the probe runs at most every
`ttl_seconds` and before a first fetch; a changed token retires every other current
snapshot of the source), `manual` and `push` never by age. A period fetched again always
gets a new snapshot (its `fetched_at` measures its age), pointing at the same
content-addressed file when the content is the same. Fetching periods records success
without moving `last_checked_at`; a probe moves it. When every requested period has a
stored snapshot, a failed fetch serves those and the widgets show stale; a period never
stored makes the run fail. The scheduler refreshes only the whole-source snapshot of due
sources; periods are refreshed when a run asks for them.

## Roles and time

All in `ada.core.services.schema`, raising `Invalid` with every problem named.

- **Declarations** (`roles.check_roles`): named columns exist; a period's ends are `date`
  or `timestamp`; a measure, its bounds and coverage are numbers; bounds come in pairs; a
  suppression flag is a boolean; a geography role names a code system and a level. Run on
  transforms' roles and on a source's declared schema.
- **Bindings and Input defaults** (`check_compatible`): a slot with a time role needs a
  bound pipeline with a time role on the same columns and, when the slot has a grain, the
  same grain; a slot with a geography role needs one on the same column with the same
  system and level. Checked in `RunService.start` and `PipelineService.add_input`.
- **Widgets** (`check_widget`, called by `WidgetService.create`): known types need a table
  output and what the spec table below says. Columns not known yet (a source registered
  without a schema) are not checked; roles always are.
- **The interval guard** (`intervals.py`): **a transform whose SQL aggregates rows may not
  declare a measure with bounds.** Aggregating means grouping, an aggregate function or a
  window over rows, or removing duplicates (DISTINCT, UNION, PIVOT), anywhere that
  produces the output rows; a subquery that only picks rows does not count. The interval
  of an aggregate is not an aggregate of the intervals, so bounds after aggregation come
  only from a statistic operator. DuckDB parses the SQL (`json_serialize_sql`); only
  transforms that declare bounds are parsed.
- **Geography** (`geo.py`): code systems `sotkanet`, `statfin`, `iso3166_numeric`; levels
  `country`, `wellbeing_services_county`, `collaborative_area`, `hospital_district`,
  `municipality`, `mixed`. Moving between systems or levels is always an explicit join
  with a mapping table.

### Reference data

Registered as project data sources like any other (`adapters/sources/examples.py`,
`REFERENCE`), so outlines and mappings carry their source, fetch time and licence in the
lineage:

| Source | Columns | Licence |
| --- | --- | --- |
| `SOTKANET_REGIONS`, `https://sotkanet.fi/rest/1.1/regions` | `sotkanet_id`, `category` (`HYVINVOINTIALUE`, `KUNTA`, `MAA`, ...), `code` (Statistics Finland's code at that level), `name`, `name_fi`, `member_of` | CC BY 4.0, THL |
| `WELLBEING_COUNTY_BOUNDARIES`, Statistics Finland's WFS `hyvinvointialue4500k`, EPSG:3067 | `county_code` (`01`–`21`, `90`, `91`), `name`, `name_fi`, `geometry` (GeoJSON text) | CC BY 4.0, Statistics Finland |

Sotkanet's measure by county, on a map (keeps Åland, which has no Sotkanet value, as
missing):

```sql
-- inputs: screening (Sotkanet), regions, boundaries
SELECT b.county_code, b.name, d.period_start, d.period_end, d.value, b.geometry
FROM input_2 AS b
LEFT JOIN input_1 AS r ON r.code = b.county_code AND r.category = 'HYVINVOINTIALUE'
LEFT JOIN input_0 AS d ON d.region = r.sotkanet_id
```

with roles `{"geo": {"code": "county_code", "system": "statfin", "level":
"wellbeing_services_county"}, "time": {"start": "period_start", "end": "period_end",
"grain": "year"}, "measures": [{"value": "value"}]}`.

## Worker tasks

Named `<module>:<function>`; the dispatcher queues them by name
(`adapters/valkey/tasks.py`) and a test checks the names match what the worker registers.

| Task | When | Does |
| --- | --- | --- |
| `ada.entrypoints.worker.tasks.sources:refresh_source` | Queued by REST, MCP, `seed-demo --refresh`, and for due sources | `SourceService.refresh(id, force)`; a failure is logged, the task ends normally |
| `ada.entrypoints.worker.tasks.sources:refresh_due_sources` | Every minute (scheduler) | Queues `refresh_source` for each source `SourceService.due()` returns |
| `ada.entrypoints.worker.tasks.runs:execute` | Queued by `TaskDispatcher.execute` | `RunService.execute(run, operator)` |
| `ada.entrypoints.worker.tasks.alerts:check_alert_rule` | Queued by `check_due_alert_rules` and `TaskDispatcher.check_alert_rule` | Skips a rule disabled after it was queued; `AlertService.check`. A failure is logged and the task ends normally (the rule stays due) |
| `ada.entrypoints.worker.tasks.alerts:check_due_alert_rules` | Every minute (scheduler) | Queues `check_alert_rule` for each rule `AlertService.due()` returns; a failure to queue one is logged and the others are still queued |
| `ada.entrypoints.worker.tasks.system:record_heartbeat` | Every minute (scheduler) | Proves scheduler, queue and worker work (health) |
| `ada.entrypoints.worker.tasks.agent:run_turn` | Queued by `AgentTurnService.post_message` after the commit (`TaskDispatcher.run_turn(turn_id)`) | `AgentTurnService.run(turn, InProcessToolbox(container))` with the application's container (see The agent). Never raises: everything is caught and logged, and a failure ends the turn `failed` |

## Dashboards

A dashboard is a live view of a project's widgets (`core/services/dashboards/`). Its
content lives in immutable versions; the `Dashboard` record points at the current one and
carries the revision.

- **Every edit adds a version.** `edit` and `pin_widget` add a `DashboardVersion`
  (`number` the previous plus one, from 1; the template id carries over) and move
  `current_version_id`. `set_default_time_range` adds no version. The dashboard row is
  updated first with `expected_revision`, so a stale caller gets `Conflict` before a
  version exists; the revision increases on every edit, pin and range change.
- **Slots.** Names are trimmed, not blank and unique within a version. A slot's widget
  must exist and be in the dashboard's project. The same widget may sit in several slots.
  `pin_widget(id, widget_id, slot)` fills the slot of that name, keeping its layout, or
  appends one.
- **Pinning copies.** The dashboard gets a widget of its own: the same operator, type,
  spec, title and note, `copied_from` set to the original, no `session_id`, created by
  whoever pins, announced with `widget.created`. Either can change later without the
  other. `copied_from` always names the original made in a session: pinning a copy copies
  its `copied_from`, so one step leads back to the session. A stale `expected_revision` is
  refused before the copy is made.
- **Layout.** `{x, y, w, h}` on a 12-column grid (`layout.py`): `x` 0–11, `w` and `h` at
  least 1, `x + w` at most 12, whole numbers, no other keys. Missing keys get `w = 6`,
  `h = 4` and a place after the previous slot of the same edit. Overlap is not checked.
- **Time range.** `start` after `end` is `Invalid`; either end may be open.
- **Viewing at one run.** A dashboard shows one run at a time: `POST
  /dashboards/{id}/runs` starts a run for its range (default: the dashboard's
  `default_time_range`), and every widget reads `GET /widgets/{id}/data?run_id=<run>`, so
  the dashboard is one consistent cut. A run is project-wide, not tied to a version.

## Reports

Reports and their versions (`core/services/reports/`).

- **The content tree.** A version's `content` is `{"blocks": [...], "sources": [...]}`.
  Blocks: `heading` (`text`, `level` 1–3), `text` (plain, a blank line starts a
  paragraph), `callout` (`text`, `tone` note / finding / warning, `title`), `widget`
  (`widget_id` in a report, `slot` in a template; `caption`), `section` (`title`,
  `blocks`; at most 4 deep). **Only widget blocks carry data**, by widget id; any other
  field is `Invalid`, with every problem and its path. At most 500 blocks, at least one.
  Defaults are filled in and nulls left out, so equal trees are stored equally.
- **Templates.** A report template's widget blocks name a declared `slot`, each exactly
  once; `create` with a `template_id` and content `{"slots": {"<slot>": "<widget id>"}}`
  fills it. A dashboard template has no tree; its slots carry the layout.
- **Versions.** A report starts at `1.0.0`. Against the latest version: **major** when the
  set of operator ids behind the widgets changed, **minor** for the same operators on
  another run or time range, **patch** when only the stored blocks differ; nothing
  different is `Invalid`. A given `bump` may be higher, never lower. Versions sort by
  number (`1.10.0` after `1.9.0`).
- **Owner.** Exactly one of `session_id` and `dashboard_id`; an owner has at most one
  report of a name.
- **Freezing.** A version pins one run (in the project) and its time range. Before it is
  stored, the run executes each widget operator, so it fixes every snapshot the widgets
  read: the version shows the same numbers for as long as it exists.
- **Generating from a dashboard.** `generate_from_dashboard(dashboard, name)` makes one
  widget block per filled slot, top to bottom then left to right, at a new run for the
  dashboard's default range (or the given `run_id` / `time_range`), and records the
  dashboard version. A dashboard that already has a report of that name gets its next
  version.
- **The sources list** is generated when a version is made and stored in its content
  (immutable, so it cannot go stale, and it keeps the address the data came from even if
  the source is edited later); `ReportService.sources(version_id)` serves it as
  `ReportSource`s, ordered by name: `data_source_id`, `name`, `address`, `access_kind`,
  `format`, `operator_id` (its lineage is the rest of the pipeline), `snapshot_id`,
  `fetched_at`, `content_hash` (of the snapshot the run used), `widget_ids`. An `input`
  operator the run binds leads to what it is bound to. A caller that sends `sources` gets
  `Invalid`.
- **Concurrency.** Adding a version moves `latest_version_id` with the report's revision,
  so two versions added at once conflict; REST and MCP also take an optional
  `expected_revision`.

## Alerts

Alert rules on a dashboard, their checks and alert instances (`core/services/alerts/`).

### The formula

`AlertRule.formula` is a JSON tree (`formula.py`). Every node has an `id` (1–64 letters,
digits, `-`, `_`; unique in the tree, so an interface can address a sub-expression) and a
`kind`; composite nodes list their operands in `args`.

| `kind` | Fields | Operands | Type |
| --- | --- | --- | --- |
| `column` | `column` | | The column's (integer and number are `number`; JSON columns cannot be used) |
| `constant` | `value`, optional `type` (`date`, `timestamp`) | | number, text, boolean, or the given type |
| `arithmetic` | `op`: `+ - * /` | 2 numbers | number; dividing by zero is NULL |
| `compare` | `op`: `< <= > >= = !=` | 2 of the same type | boolean |
| `and`, `or` | | 2 or more booleans | boolean |
| `not` | | 1 boolean | boolean |
| `previous` | `periods` (1–1000, default 1) | 1 | the operand's value that many periods earlier |
| `change` | `periods` | 1 number | the operand minus its earlier value |
| `rolling_mean` | `periods` | 1 number | the mean over the last `periods` periods; NULL until that many exist |

The root must be boolean; at most 200 nodes, 32 levels; unknown fields are errors. Time
functions need the measure's time role: a period is a row, ordered by the role's `start`
within a key. With a time role, each key's latest period is evaluated (earlier ones feed
the time functions); without one, every row. **NULL never alerts**, and suppressed values
(a measure's `suppressed` flag) never alert. Errors read `Formula node '<id>': <what is
wrong>`; the frontend marks that node. Text form, the same on server and frontend:
`value < 80 or change(value, 1 period) <= -5`.

`compile_rule(formula, schema, key_columns)` compiles it to one SELECT over `input_0` in
layers (suppression, one window layer per time function, the condition, the alerting
rows), with numbers compared as `DOUBLE`, text as quoted literals and columns as quoted
identifiers, so nothing in a formula is pasted into SQL as code. Its output has exactly
the measure's columns.

### A rule is not an operator

A rule's condition is the rule's, not a step of anyone's pipeline: nothing is added to the
operators for it, so the pipelines list and the lineage show only what people and agents
built. A check runs the compiled SQL over the measure's output in its run
(`RunService.query(run, measure, sql, limit)`, answered by the same fused query and
snapshot reuse as everything else). **Each alert keeps the SQL** (`Alert.condition_sql`,
migration `0004`), so it opens the exact rows that raised it:
`GET /api/alerts/{id}/rows` runs that SQL over the measure in the alert's `last_run_id`
(the measure's rows for alerts stored before `0004` without one).

### AlertService

- **`create_rule`** checks the dashboard, the measure (in the project, a table with known
  columns: build the rule on a transform over a source without a schema), the key
  columns, the formula, that the compiled SQL binds, and the alert pipeline (in the
  project, exactly one input slot upstream, whose declared columns are among the
  measure's).
- **`update_rule`** changes name, formula, severity, interval, enabled, key columns,
  maximum data age and alert pipeline, checks the result like a new rule, and is
  revision-checked. Interval, maximum age and alert pipeline take `Change[...]`: `None`
  clears them. New key columns resolve the old keys' alerts at the next check.
- **`check(rule_id)`**, in one unit of work: compiles the condition; refreshes
  (forced) every upstream source whose data is older than `max_data_age_seconds` (a
  failure is logged and the check goes on with the last good data); starts a run and reads
  the alerting rows (more than 10 000 fails the check); per distinct key opens a `firing`
  alert, keeps one (moving `last_run_id` and the condition), or resolves one whose key no
  longer alerts; runs the alert pipeline when an alert starts and the rule has one;
  publishes `alert.firing` / `alert.resolved`; records the check with the time it
  **started**. Everything that can fail runs before an alert is written.
- **Alert pipeline.** Runs in a run of its own, with every snapshot of the check run fixed
  into it first, so it sees exactly the check's data, and its input slot fed the alerting
  rows: `RunService.feed(run, input, check run, measure, sql)` stores them as a snapshot of
  the input for that run (`parameters_key` `run:<id>`) and fixes it there. Its failure is logged and does not undo the alerts. The alerts it was
  run for record its run (`Alert.pipeline_run_id`).
- **`due()`**: enabled rules never checked; with `check_interval_seconds`, those whose
  interval has passed; without one, those whose measure's data changed since the last
  check (any upstream snapshot newer than it; reads no data, fetches nothing).
- **`alerts(project, state)`**: newest first. **`rows(alert_id)`**: the rows that raised it.

## The agent

The agent inside the platform answers messages in sessions and in a dashboard's agent
panel (`core/services/agents/`). It works only through the MCP tools, served in process,
so whatever it makes is recorded like any client's work.

### Configuration

- **The models file.** `ADA_LLMS_CONFIG` names it (default `llms.yml` in the working
  directory; moon sets `config/llms.yml` of the checkout, the compose file
  `/config/llms.yml`, the mounted `config/`). `llms.yml` is git-ignored;
  `llms.example.yml` at the root is committed and documents the format. A missing file is
  an empty catalog: the platform runs without an agent and says so.

  ```yaml
  providers:
    gemini:
      kind: openai-compatible        # or: gemini (Google's own API)
      base_url: https://generativelanguage.googleapis.com/v1beta/openai/
      api_key_env: GEMINI_API_KEY    # the variable that holds the key
  models:
    session_agent: gemini/<model>    # answers sessions and dashboard agent panels
  ```

- **Keys** are never in the file and never returned by the API. A provider names the
  variable that holds its key (`api_key_env`; left out for an endpoint without a key).
  The full stack and `moon run :dev` pass `.env.local` to the backend and the worker. Keys
  are read once per process.
- **Checks.** The file is validated with pydantic: unknown keys are errors, an
  `openai-compatible` provider needs `base_url`, every model names a configured provider,
  purposes are known. Every problem is named with its path. The API's lifespan and the
  worker's startup read the file, so a broken one stops them at start.
- **Model ids** are `<provider>/<model>`, split at the first slash, so model names may
  contain slashes. `kind: gemini` uses pydantic-ai's `GoogleModel`; the dependency is
  `pydantic-ai-slim[openai,google]`.
- **`GET /api/llm/models`** lists them. A model whose key's variable is not set is
  `available: false`, with a `reason`.

### Turns, parts and context

`AgentTurn` (`core/models/agents.py`) is the agent's answer to one message:

```
{"id", "session_id", "prompt_entry_id", "model",
 "status": "queued" | "running" | "done" | "failed" | "cancelled",
 "parts": [Part], "error": "<text or null>", "created_at", "finished_at"}
```

Its parts are in the order they happened. They follow the AI SDK UI message parts that
the shadcn Trace component renders:

```
{"type": "reasoning", "text": "..."}
{"type": "tool", "tool_call_id": "...", "tool_name": "...",
 "state": "input-available" | "output-available" | "output-error",
 "input": {...}, "output": <json or null>, "error_text": "<text or null>"}
{"type": "text", "text": "..."}
{"type": "source", "source_id": "<data source id>", "title": "...", "url": "<or null>"}
```

A message may carry context besides its text (the chips of the chat input), stored with
its entry (`SessionEntry.context`, empty by default) and checked when it is posted:

```
{"kind": "pipeline", "operator_id": "op_..."}
{"kind": "dashboard", "dashboard_id": "...", "slot": "<name, optional>"}
{"kind": "widget", "widget_id": "..."}
```

### How a turn runs

1. **Posting.** `POST /sessions/{id}/messages` calls `AgentTurnService.post_message` in
   one unit of work: the message entry with its context; when the models file names a
   session agent (or the body names another configured `model`), a queued `AgentTurn` and
   an `agent_turn` entry (`ref` the turn id, added now so the record orders it right
   after the message); `agent.turn_started` and the task after the commit. An unknown
   `model` is 422 and nothing is stored. A configured model whose key is not set gives a
   turn that is `failed` at once with the reason ("The environment variable
   GEMINI_API_KEY is not set"), and no task. If queueing the task fails after the commit,
   the turn is marked failed ("The turn could not be queued: …").
2. **Starting.** `run_turn` calls `AgentTurnService.run(turn_id, InProcessToolbox(...))`.
   `TurnProgress.start` moves queued to running (a turn cancelled while queued is
   skipped); then `agent.turn_started` is broadcast again.
3. **The request.** `Briefing` (`briefing.py`) builds the system prompt: what ADA is, the
   project and session with ids, the panel and origin dashboards, the rules, and each
   context item explained (a pipeline to build on with its name and columns, a dashboard
   and slot to pin to, a widget referred to). The history is at most the last 40
   messages: earlier answers as their text plus one line per tool call naming what it
   made, a line per source read, and a note when they failed or were cancelled; operators
   and widgets that other clients recorded, as notes.
4. **Tools.** `InProcessToolbox` (`entrypoints/mcp/agent.py`) opens FastMCP's in-memory
   client on the platform's MCP server. Every tool call is a unit of work of its own, as
   over HTTP, so entries and widgets appear in the session as they are made.
   `get_widget_data`, `create_project` and `create_session` are left out. A tool that
   takes `session_id` gets the turn's session when the model leaves it out. A tool error
   comes back as `ToolCallFailed`, which the runtime hands to the model as a retry.
5. **Running.** `PydanticAiRuntime` (`adapters/llm/runtime.py`) builds a pydantic-ai
   `Agent` per turn: text output, the tools called one at a time, 3 retries per tool, at
   most 24 model requests. It streams each model request and each tool step and calls
   `TurnSink.checkpoint()` between steps.
6. **Parts.** Text and reasoning parts are added when they first have text and replaced as
   deltas arrive. A tool part is added when the call is made (`input-available`, the full
   arguments) and replaced at its result (`output-available` with the JSON result, or
   `output-error` with the message). After a successful tool result, every source operator
   in it (`add_source_operator`, `get_lineage`) adds a `source` part, once per data source
   per turn, with the source's name and its address when that is a URL. Every change is
   broadcast at once as `agent.turn_part`.
7. **Checkpoints.** After each step the parts so far are stored
   (`TurnProgress.checkpoint`), which also reads the cancel flag.
8. **The end.** `TurnProgress.finish` stores status, parts, error and `finished_at`; then
   `agent.turn_finished` with the status is broadcast.

- **A running turn writes through `TurnProgress`**, not the task's transaction. A turn runs
  for minutes; written in the task's unit of work, its parts would stay invisible until
  the end and its row locked, so a cancel request would wait for the turn it means to
  stop. `SqlTurnProgress` opens a short transaction per write, like `SourceCheckLog`. The
  started and finished events are broadcast right after those commits, the parts at once,
  so `AgentTurns` is the one service that holds the `EventBroadcaster`.
- **Turn writes are plain UPDATEs of their own columns**, without a revision. The worker is
  the only writer of status and parts; a cancel request writes `cancel_requested` (and,
  for a queued turn, the status, in one conditional statement). Neither overwrites the
  other, and a cancel racing a start is decided by the database.
- **Cancelling** a queued turn ends it at once (`cancelled`, `finished_at`,
  `agent.turn_finished` after the commit); a running one is flagged and stops at its next
  checkpoint; a finished one is returned unchanged.
- **Failures are readable.** "The agent did not finish within 24 steps", "The model
  provider refused the key: …", "… could not be reached: …", "… answered with an error:
  …", "The model did not answer as expected: …" (e.g. a tool that kept failing beyond its
  retries). Anything else becomes "The turn failed unexpectedly: <type>: <message>" and is
  logged with its traceback.

### Who the agent acts as

Operators and widgets the agent makes, and its turn entries, are recorded with
`Actor(kind="agent", name="<model id>")`. `acting_as(agent)` (`entrypoints/mcp/actor.py`)
sets a context variable before the in-memory client starts its server; the server's tasks
inherit it, so `calling_agent()` returns the agent. A client over HTTP runs in the HTTP
server's tasks, which never see it: whatever name it reports (including the in-process
client's, `ada-in-platform-agent`, which is only for logs), it is `external_agent`.

### The pipelines list

`PipelineService.pipelines(project)` (`core/services/pipelines/listing.py`), served by
`GET /projects/{id}/pipelines` and `list_pipelines`, is what the chat's "Add widget"
chooses from and what the agent looks at before building.

- **Which operators.** Those no other operator uses as an input, newest first:
  `{operator_id, name, kind, sources: [{data_source_id, name}], output, created_at}`.
  Alert pipelines are pipelines like any other; alert rules are not operators, so they
  never appear here.
- **Names.** A source operator by its source's name; a transform by its leading `--`
  comment lines (joined), else its whitespace-collapsed SQL, cut at 60 characters with
  "…"; an input by its slot name.
- **Sources** are listed once each, inputs first, so a diamond lists its source once.

### The dashboard's agent session

`POST /dashboards/{id}/agent-session` (`SessionService.dashboard_agent_session`) returns
the newest session whose `origin_dashboard_id` and `panel_dashboard_id` are the dashboard,
else a new one titled "<dashboard name> (agent)", announced with `session.created`. It
answers 200 when found and 201 when created.

## REST

All routes are under `/api`. Bodies are the domain models' JSON forms; request bodies
reject unknown fields. Writes to mutable records carry `expected_revision` in the body.

| Method and path | Does |
| --- | --- |
| `GET /projects`, `POST /projects {name}` | List; create |
| `GET /projects/{id}`, `PATCH /projects/{id} {name, expected_revision}` | Read; rename |
| `GET /projects/{id}/sources`, `POST /projects/{id}/sources` | List; register (`name, access_kind, address, format`, optional `options, freshness, declared_schema`) |
| `GET /sources/{id}`, `PATCH /sources/{id} {expected_revision, ...}` | Read; update the given fields. A changed address or options queues a forced refresh |
| `POST /sources/{id}/refresh {force?}` | Queue a refresh; answers 202 |
| `GET /projects/{id}/sessions`, `POST /projects/{id}/sessions {title, origin_dashboard_id?}` | List; create |
| `GET /sessions/{id}`, `PATCH /sessions/{id} {expected_revision, title?, panel_dashboard_id?}` | Read; rename or set the panel dashboard |
| `GET /sessions/{id}/entries` | The session's record, oldest first |
| `POST /sessions/{id}/messages {text, context?, model?}` | Add a message (see The agent); 201 `PostedMessage {entry, turn}`, `turn` null when no session agent is configured. An unknown `model` is 422 |
| `GET /sessions/{id}/turns`, `GET /turns/{id}` | The session's agent turns, oldest first; one turn |
| `POST /turns/{id}/cancel` | Ask a queued or running turn to stop; 202 with the turn |
| `GET /llm/models` | `ModelList {models: [{id, provider, model, purposes, available, reason}], session_agent}`; `session_agent` is a model id or null |
| `GET /sessions/{id}/widgets` | The session's widgets |
| `POST /projects/{id}/operators` | Add an operator; the body's `kind` selects source, transform or input |
| `GET /operators/{id}`, `GET /operators/{id}/lineage` | Read; the pipeline, inputs first |
| `GET /projects/{id}/pipelines` | The pipelines list (see The agent): `Pipeline[]`, newest first |
| `POST /projects/{id}/runs`, `GET /runs/{id}` | Start; read |
| `GET /runs/{id}/operators/{operator_id}/rows?limit=` | An operator's output in a run |
| `GET /snapshots/{id}` | A snapshot a run fixed (`Run.snapshots` names them by id): `fetched_at`, `content_hash`, `row_count`, `period` (`RunService.snapshot`) |
| `GET /projects/{id}/widgets`, `POST /projects/{id}/widgets` | Every widget of the project, oldest first; create |
| `GET /widgets/{id}`, `GET /widgets/{id}/data?run_id=&limit=` | Read; `WidgetData` (without `run_id` a new run is started) |
| `GET /widget-bundles/{type}.html` | A built widget (see Widgets) |
| `GET /projects/{id}/events` | The live stream |
| `GET /projects/{id}/dashboards`, `POST /projects/{id}/dashboards {name}` | List, oldest first; create |
| `GET /dashboards/{id}` | `DashboardView {dashboard, version}`: what it points at, with the revision for the next write |
| `PATCH /dashboards/{id} {default_time_range, expected_revision}` | Set the default range; `DashboardView` |
| `PUT /dashboards/{id}/slots {slots, expected_revision}` | Replace the slots (the grid's drag and resize save the full list); adds a version; `DashboardView` |
| `POST /dashboards/{id}/pins {widget_id, slot, expected_revision}` | Pin a copy of the widget (see Dashboards); adds a version; 201 `DashboardView` |
| `POST /dashboards/{id}/agent-session` | The dashboard's agent session (see The agent): 200 when found, 201 when created; `Session` |
| `GET /dashboards/{id}/versions`, `GET /dashboard-versions/{id}` | Versions, oldest first; one version |
| `POST /dashboards/{id}/runs {time_range?}` | Start the run the dashboard is viewed at; 201 `Run` |
| `GET /projects/{id}/reports?session_id=&dashboard_id=` | Reports, oldest first, optionally one owner's |
| `POST /projects/{id}/reports {name, content, run_id?, time_range?, session_id?, dashboard_id?, template_id?}` | Create; 201 with version 1.0.0 |
| `GET /reports/{id}`, `GET /reports/{id}/versions` | The report; its versions, lowest number first |
| `POST /reports/{id}/versions {content, run_id?, time_range?, bump?, expected_revision?}` | Add a version; 201 |
| `GET /report-versions/{id}`, `GET /report-versions/{id}/sources` | One version; its sources list (`ReportSource[]`) |
| `POST /dashboards/{id}/reports {name, run_id?, time_range?}` | Generate from the dashboard; 201 with the version |
| `GET /projects/{id}/templates`, `POST /projects/{id}/templates {name, kind, slots, content?}`, `GET /templates/{id}` | Templates |
| `GET /dashboards/{id}/alert-rules`, `POST /dashboards/{id}/alert-rules` | A dashboard's rules, oldest first; create (`name, operator_id, formula, key_columns`, optional `severity, check_interval_seconds, max_data_age_seconds, alert_pipeline_id`) |
| `GET /alert-rules/{id}`, `PATCH /alert-rules/{id} {expected_revision, ...}` | Read; change. Fields left out stay; `null` clears `check_interval_seconds`, `max_data_age_seconds` and `alert_pipeline_id` |
| `POST /alert-rules/{id}/check` | Check now, in the request: `{rule, changed, firing}` |
| `GET /alerts/{id}/rows?limit=` | The rows that raised the alert, in its last run |
| `GET /projects/{id}/alerts?state=`, `GET /dashboards/{id}/alerts?state=` | `AlertView[] {alert, rule}`, firing first, newest first within a state |
| `GET /projects/{id}/alert-rules` | `{dashboard, rules}[]` for every dashboard of the project |

- **Status codes.** 201 for a create (including a message, a pin, a dashboard run, a
  report or version, a new agent session), 202 for a queued refresh and a turn cancel,
  200 otherwise. Errors are `{"detail": "..."}` with
  404 for `NotFound`, 422 for `Invalid` (and malformed bodies; a formula error's detail
  names the node; an unknown widget inside report content is 422, not 404), 409 for
  `Conflict`, 503 for `Unavailable`. A 409 adds `expected_revision` and `revision`.
- **Who is acting.** There are no users: requests from the frontend act as
  `Actor(kind="user", name="web")`.

## MCP tools

Tool names are snake case and start with a verb (`list create register update refresh
add get preview system pin edit set show generate check`; `tests/test_api_mcp.py`). Tools
that create something in a session take an optional `session_id` and a `note`: one line
on why the agent is doing this, shown in the session. The acting `Actor` is
`external_agent` with the client name the MCP host reported when it connected; the
in-platform agent's calls act as `agent` with its model id (see The agent).

| Group | Tools |
| --- | --- |
| Projects, sources | `list_projects`, `create_project`, `register_source`, `list_sources`, `update_source`, `refresh_source` |
| Sessions, pipelines | `create_session`, `add_source_operator`, `add_transform`, `list_pipelines` (the pipelines list: look there before building), `get_lineage`, `preview_operator` |
| Widgets | `create_widget`, `list_session_widgets`, and `get_widget_data` for the widget itself (MCP Apps visibility `app`) |
| Dashboards | `create_dashboard`, `list_dashboards`, `get_dashboard`, `list_dashboard_versions`, `pin_widget` (its description says the dashboard gets a copy), `edit_dashboard`, `set_dashboard_time_range` (ISO dates), `show_dashboard_in_session` (the session's revision). They return `{dashboard, version, url}` |
| Reports | `create_report`, `add_report_version`, `generate_report_from_dashboard`, `list_reports`, `get_report` (optional `version`), `create_template`, `list_templates`. They return `{report, version, versions, url}` |
| Alerts | `create_alert_rule` (its description carries the formula format), `list_alert_rules`, `get_alert_rule`, `update_alert_rule` (a `clear` list empties the interval, maximum age or alert pipeline), `check_alert_rule` (`{rule, changed, firing}`), `list_alerts` (`{alert, rule_name, severity, dashboard_id, url}`) |
| System | `system_status` |

Tools return ids and small previews, never whole datasets. A tool that produces a widget,
dashboard or report returns its address in the frontend. Writes to mutable records take
the `expected_revision` the agent read; a mismatch is a tool error naming both revisions.
The core's errors come back as tool errors with their message; `Unavailable` adds that it
is temporary and to try again later.

### Widget specs

`create_widget` takes a `type` and a `spec` of that type's settings, all optional. A
widget whose operator lacks what its type needs is refused, with every problem named.

| Type | Spec keys | Needs |
| --- | --- | --- |
| `value` | `column` (default: the first measure role, else the first numeric column), `label` (default: the column name), `unit`, `decimals`. Shows the latest period when the output has a time role, else the last row | `column` if given exists and is numeric; else a measure or a numeric column |
| `table` | `columns`: the column names to show, in order (default: all) | every name exists |
| `line-chart` | `x` (default: the time role's start, else the first date column), `y`: one column (default: the first measure role, else the first numeric column), `series`: a column whose values split the lines | `x`, `series` exist; `y` numeric; else a measure or a numeric column other than x |
| `map` | `value` (as `value`'s `column`), `geometry` (default `geometry`: GeoJSON outlines, joined from the boundaries reference source), `label` (default: a column `name`, else the code). Shows each region's latest period | a geography role whose level is not `mixed`; the geometry column (json or text); `label` if given exists; a value as for `value` |

## Live events

`GET /api/projects/{id}/events` is a server-sent event stream. Each message is

```
event: <EventType value>
data: <the Event as JSON>
```

Payloads carry ids only; the client fetches what it needs. The types are in
`ada/core/models/events.py`. A comment line is sent after 15 quiet seconds to keep the
connection open. Events are broadcast after the unit of work that caused them commits.
`agent.turn_part` is the exception to both: it carries content and is sent at once.

| Event | Payload |
| --- | --- |
| `session.created` | `session_id` |
| `session.entry_added` | `session_id`, `entry_id` |
| `widget.created` | `widget_id`, `session_id` if any |
| `run.started`, `run.finished`, `run.failed` | `run_id`, `operator_id`; `error` on failure |
| `source.refreshed`, `source.refresh_failed` | `data_source_id`, `changed` (any period's content too); `error` on failure |
| `dashboard.changed` | `dashboard_id`, `version_id` (the new version for an edit or pin; the current one, or null, for a new dashboard or a range change) |
| `report.version_created` | `report_id`, `version_id`, `version` |
| `alert.firing`, `alert.resolved` | `alert_id`, `rule_id` |
| `agent.turn_started` | `session_id`, `turn_id`. After the commit that queued the turn, and again after the one that started it |
| `agent.turn_part` | `session_id`, `turn_id`, `index`, `part` (the whole part). At once, not after a commit: token deltas cannot be fetched afterwards. A part with the same `index` replaces the earlier one (text grows; a tool's state moves on) |
| `agent.turn_finished` | `session_id`, `turn_id`, `status`. After the commit that stored the final turn |

A client that connects late reads `GET /turns/{id}` and then applies parts with a higher
index.

## Widgets

A widget type is a folder `services/widgets/src/widgets/<type>/`, built into one
self-contained file `dist/<type>.html`: `value`, `table`, `line-chart`, `map`. `any` is the
one bundle that renders every type, picked by the widget's `type`. A widget never
receives data from an agent; it asks the server for the output of its operator.

- **Where the built files are.** `WIDGETS_DIR` (default: `services/widgets/dist` of the
  checkout; moon sets it; `/app/widgets` in the backend image, which builds them).
  `GET /api/widget-bundles/<type>.html` serves a file that exists there; names other than
  `[a-z0-9][a-z0-9-]*` are 404, so no path leaves the directory.
- **In the frontend.** The frontend loads
  `<base>/<type>.html#widget=<id>&run=<run>&theme=<light|dark>` in an iframe, `run` and
  `theme` optional, with the base from `VITE_WIDGETS_URL`: the widgets dev server in
  development, `/api/widget-bundles` otherwise. Inside a frame `prefers-color-scheme`
  follows the system, not the page, so `theme` is set when the person picked a theme apart
  from the system's; the widget (`followTheme` in `host.ts`, and `styles.css`) applies it
  and follows hash changes, so switching needs no reload. Without it, page and widget both
  follow the system. The widget reads
  `GET /api/widgets/{id}` and `GET /api/widgets/{id}/data` on the same origin.
  `WidgetData.output` is the operator's output schema, so the roles need no third request.
  **One run per view.** Every page shows its widgets at one run, which it passes to every
  card, frame and pipeline preview explicitly: a report its version's run; a dashboard
  (and the dashboard panel beside a session) the dashboard's run for its range; a session
  one run of the project without a range (`POST /projects/{id}/runs`); a widget page the
  run named by `?run=`, else one of its own like a session's. A frame never starts a run:
  until the page's run is there the card says it is starting. When the live stream says
  data changed (the widget epoch), a following page starts a new run (`useViewRun` in
  `lib/view-run.ts`) and the frames reload by their new address; a frozen run (a report,
  `?run=`) never changes.
- **The card.** The type is a badge in the header; the title is plain text. The footer is
  one line: at the left "Pipeline" with an open-in-a-popup icon, one button that opens the
  pipeline view (the lineage is read only when it opens); at the right icon actions with
  tooltips (their accessible names): "Open full size" (unless already full size), then
  "Add to dashboard" (the pin chooser, opening below the line; it says the dashboard gets
  a copy) wherever the widget is not on a dashboard, and on a dashboard "Go to the session
  it came from". That uses the widget's `session_id`, else its original's (`copied_from`,
  read with `GET /widgets/{id}`), and links to `?widget=<that widget's id>`; it is
  disabled with "Not made in a session" when neither has one.
- **Full size.** `?open=<widget id>` on any page of a project (checked on the project's
  layout route) shows the widget in a modal over the page (`components/widget-modal.tsx`).
  "Open full size" (`open-widget-link.tsx`) pushes the address and puts the card's run in
  the history entry's state (`openRun`), so the modal shows the same numbers. Closing
  (Escape, ×) goes back in history, as does the browser's back; the page beneath was never
  unmounted, so its scroll position is kept. A direct link to `?open=` has no run in its
  state: the modal starts a run of its own, like the widget page, and closing replaces the
  address without `open`.
- **The pipeline view** is a modal dialog (`components/pipeline/`): the operator tree as a
  graph laid out by depth (sources at the left, the widget's operator at the right, a
  shared input drawn once; materializing nodes solid and tinted, pass-through dashed;
  nodes are buttons, the arrow keys follow the edges), the selected operator's details
  (kind, id, parameters, output schema with its roles, who made it, and for a snapshot in
  the card's run its fetch time, content hash and row count from `GET /snapshots/{id}`),
  and its first 50 rows in the card's run (`GET /runs/{id}/operators/{op}/rows?limit=50`).
  A line at the top says which run that is: "Frozen: report version 1.1.0, run …" or
  "The dashboard's current run, follows new data". The view never starts a run.
- **In an MCP host (MCP Apps).** Every bundle is a resource `ui://ada/widgets/<type>.html`
  (`text/html;profile=mcp-app`), and `create_widget` names `ui://ada/widgets/any.html`
  as its UI. With no fragment and a parent frame, the runtime speaks the MCP Apps
  protocol over postMessage: `ui/initialize`, then `ui/notifications/initialized`; it
  takes the widget from the `ui/notifications/tool-result` of `create_widget` and calls
  `get_widget_data` with `tools/call` through the host. No REST is used there.
- **What it must show.** A marker when `is_scenario` is true, and one when `is_stale`
  is true. A simulated or outdated number must never look like a measured, current one.
- **The map.** Each region at its latest period, in five equal classes on a sequential
  blue ramp (more is darker; flipped in dark mode); suppressed regions hatched, regions
  without a value grey, neither a colour of the scale. One focus stop; the arrow keys step
  through the regions, a status line reads them, and a visually hidden table lists them.
  Planar coordinates (EPSG:3067) are drawn as they are; longitude and latitude are
  corrected by the middle latitude. Outlines come as data, not with the bundle.
- **Access to the host.** All of the above goes through `services/widgets/src/lib/host.ts`.

## The frontend

### Look and layout

- **shadcn/ui** (CLI 4.23): style `radix-nova` (Radix primitives), Tailwind 4, neutral,
  lucide icons (`components.json`). The components in `src/components/ui/` are exactly as
  the CLI wrote them, except `hooks/use-mobile.ts` (useSyncExternalStore instead of state
  set in an effect, which lint flags); the code block's syntax highlighter (and `shiki`)
  is left out.
- **Theme.** shadcn switches colours on a `.dark` class. `lib/theme.tsx` sets it from the
  person's choice (light, dark, or as the system, remembered in `localStorage`
  `ada-theme`), with a script in `index.html` so a dark page does not flash light. The
  theme menu is the sun or moon at the top right. Widget frames follow it (see Widgets).
- **Sidebar** (`components/project-sidebar.tsx`), after shadcn's sidebar that collapses
  to icons (`collapsible="icon"`). Its header is the project switcher: the project's name
  opens a menu of the projects and "All projects". Then Overview; Sessions (with a new
  session dialog), Dashboards (a new dashboard dialog) and Reports (a link to
  `/reports/new`), each a collapsible item listing its items; Alerts, one link with the
  firing count; and Data sources, folded at first (each links to its card on the overview,
  `#source-<id>`, marked when its last refresh failed). Sessions and reports newest first.
  The current item is marked (`data-active`, and the router's `aria-current="page"`).
  Collapsed, the icons have tooltips and a type's icon opens the sidebar again. Toggled by
  the top bar's button, the rail or Ctrl/Cmd+B; a sheet on phones.
- **Pages** fill the width under a top bar with the sidebar toggle, the live indicator and
  the theme menu; each page scrolls inside.
- **Type labels, no breadcrumbs.** Every page shows its type with the sidebar's icon above
  its title (`PageType`, `PageHeader` in `components/page-header.tsx`; icons and labels in
  `lib/page-types.ts`).
- **Icons.** Icons instead of words where clear (dialog close, rename, version view and
  restore, alert rule check and edit, pin, open full size, go to session, detach, stop,
  send); primary actions keep a word and an icon ("Add widget", "Generate report", "Edit
  layout"). `IconButton` (`components/icon-action.tsx`) is an icon-only button whose
  tooltip is also its `aria-label`, disabled with `aria-disabled` and a reason so the
  keyboard still reaches it; `Hint` puts a tooltip on any control. Every icon-only control
  has a name and a tooltip.
- **Rename** is a pencil ("Rename"): Enter saves, Escape cancels (without closing a dialog
  around it), the check and × save and cancel by pointer.
- **Dialogs** (`components/modal.tsx`, shadcn's Dialog with an × "Close"): focus moves in
  (to `[data-autofocus]`, else the dialog itself, so no tooltip opens by itself and the
  first Escape closes the dialog), stays inside and returns to the opener; Escape and a
  click outside close; the page behind is `inert` as well as `aria-hidden`.

### Chat

- **The record** (`components/session-record.tsx`): the person's messages as bubbles on
  the right with their context chips (named from what they point at), other actors' on
  the left, agent turns (`agent_turn` entries) as the agent's answers, and operators and
  widget cards as before. It follows the bottom while the person is there (new entries,
  streaming text) and stays put when they scrolled up; `?widget=` scrolls to a widget and
  marks it.
- **An agent turn** (`components/chat/agent-turn.tsx`) is read with `GET /turns/{id}`.
  Consecutive parts that are not text form one shadcn Trace: reasoning ("Thinking" open
  while it streams, "Thought" folded after), tool calls ("Calling / Called / Failed:
  <tool>", opening to their input and output or error as JSON), neighbouring sources as
  one line ("Used n sources", each a link when it has a URL). Text parts are the answer
  between them. Queued, running without parts, failed (with the error, `role="alert"`)
  and cancelled are said.
- **Streaming** (`lib/agent-turns.ts`, `lib/events.ts`, `lib/live.ts`): `agent.turn_part`
  puts the part at its index into the cached turn. Parts of running turns are also kept
  aside, and a fetched turn gets those with a higher index than it has, so a refetch that
  lags behind the stream drops none. `agent.turn_started` and `agent.turn_finished`
  refetch the record and the turn; a finished turn's kept parts are forgotten. A reconnect
  forgets all kept parts and refetches everything.
- **The composer** (`components/chat/composer.tsx`): Enter sends, Shift+Enter is a new line
  (Enter ending an IME composition does not send). The body is `{text, context, model?}`,
  the chips' contexts flattened; chips are removable. A model picker lists
  `GET /api/llm/models`, default `session_agent`, unavailable models disabled with their
  reason; `model` is sent when the models are known. While the latest turn is queued or
  running, a stop button posts `POST /turns/{id}/cancel`. Without an agent
  (`session_agent` null or unavailable, or a post answered with `turn: null`) the message
  is still recorded and a note says nobody will answer and how to configure
  `session_agent` in `llms.yml`. If the models route fails, the picker and the note are
  left out and the message is sent without `model`.
- **Add widget** (`components/chat/add-widget.tsx`): a Popover with a Command over the
  pipelines list, searchable by name, source names and column names. Choosing one adds a
  chip. One chip may carry several contexts (`chat-draft.ts`): on a dashboard the
  pipeline and `{kind: "dashboard", dashboard_id, slot?}` together, removed together; no
  slot means a new one. The draft lives on the page, so "Add widget" elsewhere on the page
  fills the composer, which then takes the focus.

### Dashboards and the panel beside a session

- **The agent panel** (`components/dashboards/agent-panel.tsx`) is docked at the right of a
  dashboard, closed at first (opening it finds or creates the agent session, which a mere
  look should not do), and remembered per browser (`localStorage`
  `ada-dashboard-agent-panel`). Opening it posts `POST /dashboards/{id}/agent-session`
  once per page (`dashboardSessionQuery`, not under `['dashboards', id]`, so dashboard
  events do not post again) and shows that session's chat; a link opens it as a session.
  "Add widget" in the header (a new slot) and in empty slots (that slot) adds the chip and
  opens the panel.
- **Layout editing** (`components/dashboards/dashboard-grid.tsx`, `layout.ts`): "Edit
  layout" shows two handles per slot, on its corners: move and resize. Rows are 80 px, the
  gap 16 px, and a widget fills its cell. Dragging previews the layout; others in the way
  move down (never up or sideways). Maps keep their aspect ratio (the pixel ratio when the
  resize began; the width decides, or the height when only it changed). Minimums: value
  2×2; table, line chart and map 3×3; empty 2×2. Escape during a drag puts it back. Drops
  change only the page's draft layout ("unsaved layout changes" next to the version);
  **Done** saves the draft once, as one new version, with `PUT /dashboards/{id}/slots` and
  `expected_revision`; a 409 reads the dashboard again, says so, and keeps the draft and
  the editing mode, so Done can be pressed again. An × discards the draft. While a draft
  exists, leaving the page in the app asks first (`useBlocker`) and so does closing or
  reloading the tab (`beforeunload`). Keyboard: Enter or Space on a handle picks the slot
  up, the arrows move or resize by one cell, Enter or Space drops, Escape or leaving the
  handle puts it back; a live region says what happens.
- **Handles need the 12-column grid**, a container at least 48rem wide, and never show on
  an old version. The hint above the grid says how to drag; in a narrower grid (one
  column, including a laptop with the agent panel open) it says the grid is too narrow to
  arrange and to widen the window or close the agent panel.
- **A dashboard beside a session** splits the page half and half (`lg` and up; stacked
  below): the conversation, and the dashboard under a black bar (both themes) saying
  "DASHBOARD" and its name (a link to it), with an × "Detach the dashboard" that sends
  `PATCH /sessions/{id} {panel_dashboard_id: null, expected_revision}`; the conversation
  then takes the full width. The half shows the dashboard's grid, read only, in one column
  when the half is narrow. Its empty slots offer "Add widget" into the session's composer,
  with the dashboard and slot.

## Frontend routes

| Path | Shows |
| --- | --- |
| `/` | Projects |
| `/projects/{id}` | A project's overview: counts per kind, the five newest sessions with the dashboard beside them, and the data sources with their state (`#source-<id>`). The lists of dashboards, reports and alerts are in the sidebar; widgets are not listed on their own |
| `/projects/{id}/sessions/{session_id}` | A session: its record as a chat with its widget cards, all at one run of the page (each can be added to a dashboard), the composer, and its panel dashboard beside it at the dashboard's run, which can be detached; `?widget=<id>` scrolls to one. MCP tools return this address for widgets made in a session |
| `/projects/{id}/widgets/{widget_id}` | One widget on its own page, at `?run=` when given, else at one run of the page; the address MCP tools return for widgets made outside a session. In-app links open widgets full size instead (`?open=`) |
| `/projects/{id}/dashboards/{dashboard_id}` | The slots on the grid, all on one run; firing alert badges; the time range control (whole years; "Show" starts a run, "Save as default"); "Edit layout"; "Add widget" and the agent panel; "Generate report"; version history with view (`?version=n`) and restore; start a session from it |
| `/projects/{id}/reports/{report_id}` | A report version (`?version=1.2.0`, default the latest): its tree with each widget at the version's run (opening full size at that run), the run, range, dashboard version, the sources list; each card's pipeline view previews the version's run |
| `/projects/{id}/reports/new` | Generate a report from a dashboard (`?dashboard=<id>` preselects it) |
| `/projects/{id}/alerts` | The alert feed (all, firing, resolved; each alert opens its alerting rows) and the rules by dashboard, with the rule editor and its formula builder |
| `?open=<widget id>`, on any of the project's pages | The widget full size in a modal over the page (see Widgets) |

A write the page makes carries the revision it last showed; a 409 reads the record again
and says so. The query keys are in `lib/api` (`keys`, `dashboardKeys`, `reportKeys`,
`alertKeys`, `runKeys`, `agentKeys`); `lib/events.ts` maps each live event to the keys it
makes stale, except `agent.turn_part`, which goes into the cached turn. Every widget card
has the footer and pipeline view of "Widgets" above, at its page's run.

The API types are generated from the backend's OpenAPI schema (`Schemas[...]`, the typed
`api` client in `lib/api/client.ts`); the agent's calls are in `lib/api/agent.ts`. Only
the live stream's types are written by hand (`lib/api/models.ts`), since the schema does
not describe it.

## Tests

- Backend tests run without services, except those that take the `database_url` or
  `migrated_database_url` fixture (PostgreSQL) or the Valkey fixtures of
  `tests/test_events_valkey.py` and `tests/test_worker_dispatcher.py`. They need
  `moon run root:infra` and are skipped locally when it is not running; with `CI` set
  they fail instead. CI starts both.
- The composition root binds PostgreSQL and Valkey. A test that builds the app, the MCP
  server, the worker or a container passes the in-memory adapters from `tests/memory.py`
  (`MemoryBackground` for events and tasks, `MemoryRepositories` for the repositories and
  source locks) unless it means to use the real service.
- `tests/factories.py` builds models with defaults. `tests/fakes.py` has a clock that
  stands still, a source reader that returns what it is told, and an analysis store that
  runs no SQL. `tests/time_world.py` and `tests/alerts_support.py` set up the pipelines
  of the time and alert tests.
- No test calls an external service. Source readers are tested against recorded
  responses (`tests/recordings`, replayed by `Replay` in `tests/test_sources_examples.py`).
- `tests/test_end_to_end.py` drives both slices over MCP against PostgreSQL, the DuckDB
  store and recorded answers, with the worker's tasks in an in-memory broker: NORDCAN to a
  table widget; and Sotkanet pushed down to a dashboard's years, mapped to the counties on
  a map, a report and its minor version, and an alert rule that fires for four counties
  and resolves when the next (recorded, then raised) answer recovers.
- **The agent.** Tests never read the developer's models file: `tests/conftest.py` points
  `ADA_LLMS_CONFIG` at a file that does not exist. The agent tests use pydantic-ai's
  `FunctionModel` (`tests/agent_support.py`: a scripted model whose steps call tools or
  stream text). One test uses a real OpenAI client against `127.0.0.1:1` with retries
  off, to check the unreachable provider without any network.
- The frontend's API types are generated: `moon run frontend:generate` after the routes
  change, and commit `openapi.json` and `schema.d.ts`.
- The frontend's tests are Vitest with mocked fetch and EventSource, a few seconds in all
  on a quiet machine. A few long user flows render the whole app through the real routes
  (`renderAt`, `serveApi` and the fixtures in `src/test/app.tsx`), one file per area:
  `project`, `session`, `dashboard`, `reports`, `alerts` in `src/test/`. Beside the code,
  unit tests guard the logic: the formula builder, the pipeline graph's layout, the
  dashboard layout, agent-turn parts, live event effects, the live connection and widget
  frames. Under Vitest the routes are not code-split (`vite.config.ts`), so a file loads
  them while it is imported rather than inside its first test; the async utilities wait up
  to 5 s (`setup.ts`) and a test up to 15 s. `setup.ts` also adds what jsdom lacks for
  Radix, cmdk and the sidebar.
- The widgets' tests check each widget's model and drawing (the map's classes and legend
  most) and the runtime: loading from the page's address or from an MCP host, and the
  theme.
- **The development mock** (`src/dev/mock-agent.ts`): in a dev build only, and only with
  `?mock-agent=1` (until `?mock-agent=0`, kept in `sessionStorage`), it answers the
  agent's routes from memory (models, pipelines derived from the project's widgets,
  messages and turns, dashboard agent sessions) and streams a scripted turn as live
  events on the page's own stream. Nothing it answers reaches the backend; every other
  request goes through. A production build does not contain it.

| Package | Holds | May import |
| --- | --- | --- |
| `ada.core.models` | Domain models | nothing of ours |
| `ada.core.ports` | Outbound ports: what the core needs from the outside | models |
| `ada.core.services.ports` | Inbound ports: the use cases | models, outbound ports (a use case may take one its caller provides, as `AgentTurnService.run` takes the toolbox) |
| `ada.core.services` | The use cases' implementations | models and both kinds of ports |
| `ada.adapters` | Implementations of outbound ports: PostgreSQL, Valkey, DuckDB, HTTP, the language models (pydantic-ai) | models, outbound ports |
| `ada.entrypoints` | HTTP, MCP, worker, CLI | models and both kinds of ports, resolved through the container. The worker also imports the MCP entrypoint: the agent's tools are the MCP tools, served in process || `ada.composition` | Binds every port to its implementation | everything |

Two stores, with different jobs:

- **PostgreSQL** holds definitions: projects, operators, runs, dashboards, reports, alerts.
  Access goes through SQLAlchemy; Alembic migrations live in `ada/adapters/db/migrations`.
- **Parquet files queried with DuckDB** hold analysis data. A snapshot is written once and
  never changed, and every process reads the files with its own in-memory DuckDB, so the
  API and the workers do not contend for one database file.

Background work (runs, source refreshes, alert checks, agent turns) goes through taskiq
with Valkey as the broker. There is exactly one scheduler.

## Demo data

`ada seed-demo` (`entrypoints/cli/seed.py`) creates the project "Nordic cancer care" with
the five example sources and, idempotently, a ready demo: a session that maps Sotkanet's
breast cancer screening participation to the wellbeing services counties for the latest
year with their boundaries; a map and a table of it on the dashboard "Screening
participation" (2022–2024) shown beside the session; the alert rule "Participation below
80 %" on it; and a line chart of lung cancer survival in Finland from NORDCAN. Everything
is found by name (operators by identity) and only what is missing is added; a source an
older seed registered differently is registered anew, the old one kept under a dated name.
`--refresh` fetches what the demo shows in the command's own process (a handful of
requests), generates the report "Screening participation report" once, checks the rule,
and queues the remaining sources for the worker.

## Known issues, for the next wave

- **Widget frames share the API's origin.** The frontend frames widgets with
  `sandbox="allow-scripts allow-same-origin"` from `/api/widget-bundles`, the API's own
  origin (the browser warns about it in the console). A sandbox with both flags on the
  same origin can remove its own sandbox, so a widget bundle can do anything the page can.
  The bundles are our own code, so this is no hole today, but it must not stay that way
  once widgets render anything less trusted. Options: serve the bundles from a separate
  origin, or drop `allow-same-origin` and hand the widget its data over postMessage, as in
  an MCP host.
- **An alert pipeline's run counts as a scenario.** `Run.is_scenario` is true for any
  binding, so the run of an alert pipeline, whose only binding is the alerting rows, is
  flagged as a scenario and its widgets would say "simulated". Bindings that simulate and
  bindings that feed an alert pipeline need telling apart.
- **Union snapshots accumulate.** They are a cache keyed by content, retired only by a
  probe change or a forced refresh, like materialized transforms. Every page view starts a
  run, and another one whenever data changes (widget data without a run, as an MCP host
  asks for it, starts one each time); runs accumulate too. Nothing prunes them yet.
- **Editing a source's declared schema does not reach its pipelines.** The source operator
  keeps the output it was registered with (operators never change). Register the source
  anew instead, as `seed-demo` does.
- **A report's source address is the registered one.** With pushdown, the periods actually
  asked for are the version's time range, not the years in the address.
- **The MCP Apps bridge is untested against a real host.** It follows the MCP Apps
  protocol (`ui/initialize`, `ui/notifications/tool-result`, `tools/call`, version
  `2026-01-26`) and is tested against a fake host frame only. Not done: the
  `ui/notifications/tool-input`, `host-context-changed` and teardown messages, size
  reporting to the host, theming from the host context, and a CSP declaration on the
  resources. `get_widget_data` is marked for the app only, but FastMCP still lists it to
  every client.
- **`source.refresh_failed` follows the caller's transaction.** The failure record is
  committed at once, but the event goes out only if the caller commits. `last_error` is
  cleared only by a fetch or probe that succeeds; a run whose periods are all fresh leaves
  an earlier error, and the widgets keep showing stale.
- **After-commit actions are not retried.** If queueing the refresh that follows a source
  edit fails after the commit, it is logged and lost.
- **Source locks can deadlock across sources.** Two units of work that both fetch the same
  two sources in opposite orders wait on each other; PostgreSQL aborts one, which fails
  with an error. Pipelines read their sources in a fixed order, so it needs two different
  pipelines fetching at the same moment.
- **Alert checks.** Two checks of one rule at once (scheduled and "Check now") can both
  open an alert for a key; `uq_alerts_firing` rejects the second check, and the rule is
  due again on the next tick. A disabled rule keeps its firing alerts until it is enabled
  and checked. `AlertRepository` has no listing per rule; a check filters the project's
  firing alerts. The alert pipeline's summary is not attached to the alert event yet.
- **Time.** A range without a start is not pushed down (the source is read whole and
  filtered). `refresh_range` lists all of a source's snapshots to find the newest period:
  fine for years, slow for thousands of periods. The map's equal classes put most regions
  in one class when one region is an outlier; a quantile option can come later.
- **Dashboards and reports.** The dashboard beside a session is read only; its layout is
  edited on the dashboard page. Moving a slot changes the DOM order after the save
  (reading order), which reloads the moved frames once. Sessions do not record reports in
  their entries (`EntryKind` has no report kind); a session's reports are listed by
  `?session_id=`.
- **A turn keeps a connection idle.** `run_turn` reads the turn, the session and its record
  through the task's request scope, which keeps one pooled connection idle in a
  transaction until the turn ends (minutes). Harmless for correctness (no locks beyond
  reads); reading them in a scope of their own would free it.
- **A worker killed mid-turn leaves the turn `running`.** Cancellation by the process
  (`CancelledError`) is not caught, and nothing sweeps stale running turns. A sweep (e.g.
  running turns with no checkpoint for some minutes become failed) would fix it.
- **Two messages in quick succession run two turns at once**, each with the history it
  found; the second does not wait for the first's answer.
- **The agent's history is bounded by count (40 messages), not by tokens**, and tool
  results are given to the model in full (a long `get_lineage` costs tokens). Earlier
  answers keep only a one-line summary per tool call.
- **Token deltas are broadcast one event each.** Fine for a demo; a busy model may want
  them batched.
- **Source parts come only from source operators in tool results** (`add_source_operator`,
  `get_lineage`); reading a pipeline's data through `preview_operator` does not add one.
- **The agent's text is plain text.** The record does not render Markdown yet.
- **The models file is read once per process.** Changing it or a key means restarting the
  backend and the worker.
- **The image runs as the user `ada` (uid 1000)**, so a `config/llms.yml` that only its
  owner may read stops the backend at start ("could not be read as YAML: Permission
  denied") on a Linux host; Docker Desktop's bind mounts do not have this problem.
- **No authentication.** Whoever can reach the gateway can use the API and the MCP
  endpoint.

## Documents

| File | What it is |
| --- | --- |
| `docs/spec.md` | The design: what the system does and why |
| `docs/contracts.md` | Where things live and how the parts talk to each other |
| `docs/plan.md` | The order of work and how it is split |

## Configuration

Settings come from the environment (`services/backend/src/ada/config.py`).

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL of the PostgreSQL database, e.g. `postgresql+psycopg://…` |
| `VALKEY_URL` | Valkey URL, e.g. `redis://…` |
| `DATA_DIR` | Directory for snapshots (default `data`; `/data` in the image) |
| `WIDGETS_DIR` | The built widgets (default `services/widgets/dist` of the checkout; `/app/widgets` in the image) |
| `ADA_LLMS_CONFIG` | The agent's models file (default `llms.yml`; moon: `config/llms.yml` of the checkout; compose: `/config/llms.yml`, the mounted `config/`). See The agent |

There are no users and no authentication yet: whoever can reach the gateway can use the
API and the MCP endpoint. Do not expose it publicly as it is.

Secrets never go into the repository. `.env` holds only `VERSION`; put local secrets,
such as the model providers' keys, in `.env.local`, which git ignores and the compose file
passes to the backend and the worker. The models file is git-ignored too.
