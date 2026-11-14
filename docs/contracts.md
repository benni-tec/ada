# Contracts

What the workstreams of `docs/plan.md` agree on. These are fixed for a wave: if one
turns out wrong, report it instead of changing it, so everyone changes together.

The spec (`docs/spec.md`) says what the system does and why. This file says where things
live and how the pieces talk. It describes the code as integrated after wave 1.

## Frozen code

Do not edit these; build against them.

| Path | What it is |
| --- | --- |
| `ada/core/models/**` | The domain models |
| `ada/core/ports/**` | Outbound ports: repositories, analysis store, source readers and the check log, events, tasks, transactions, clock |
| `ada/core/services/ports/**` | Inbound ports: one service per use-case group |
| `ada/adapters/db/tables.py`, `ada/adapters/db/migrations/**` | Every table, in one migration. Nobody adds a migration during a wave |
| `ada/discovery.py`, `ada/composition/__init__.py`, `ada/composition/unbuilt.py` | How features register themselves |
| `tach.toml` | Module boundaries. They are per package, so new files in an existing package need no change |

## Adding a feature without touching shared files

Four packages are scanned at startup. A feature adds a module; no list is edited.

| To add | Create a module in | It must expose |
| --- | --- | --- |
| REST routes | `ada/entrypoints/http/routers/` | `router = APIRouter(route_class=DishkaRoute, tags=[...])` |
| MCP tools | `ada/entrypoints/mcp/tools/` | `register(mcp, inject)`, defining tools with `@mcp.tool` and `@inject` |
| Worker tasks | `ada/entrypoints/worker/tasks/` | functions decorated with `@task(...)` from `ada.entrypoints.worker.registry` |
| Bindings | `ada/composition/providers/` | `provider`, a dishka `Provider` instance |

### Who binds what

Every port is bound in exactly one provider module. Ports nobody has implemented yet are
bound to a stand-in (`unbuilt(Port)`): the application starts, and using the port raises
`NotImplementedError` naming it. Implementing a port means replacing its binding in the
module that already holds it.

| Provider module | Ports | After wave 1 |
| --- | --- | --- |
| `infrastructure.py` | Settings, database engine and request session, `AfterCommit` (`PendingWork`), Valkey client, `Clock` | Real |
| `system.py` | `Database`, `TaskQueue`, `SystemStatusService` | Real |
| `repositories.py` | All twelve repositories (SQLAlchemy, on the request's session); `SourceCheckLog` (own connection) | Real |
| `analysis.py` | `AnalysisStore` (Parquet and DuckDB), `PipelineService`, `RunService` | Real |
| `sources.py` | `SourceReaders` (HTTP: URL and request sources), `SourceService` | Real |
| `workspace.py` | `ProjectService`, `SessionService`, `WidgetService` | Real |
| `background.py` | `EventBroadcaster` (Valkey pub/sub), `EventPublisher` (transactional, per request), `EventStream` (Valkey), `TaskDispatcher` (taskiq on Valkey) | Real |
| `dashboards.py`, `reports.py`, `alerts.py` | Their services | Stand-ins until wave 2 (G, H, I) |

Services are bound at `Scope.REQUEST`; whatever holds a connection or shared state at
`Scope.APP`. The in-memory repositories, event bus and task dispatcher in
`ada/adapters/memory` are no longer bound by default; tests bind them (below).

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
  queue the forced refresh.

## Behaviour every implementation of a port must share

The in-memory repositories (`ada/adapters/memory/repositories.py`) are the reference, and
`tests/test_memory_repositories.py` states the expectations. The database repositories
pass the same ones (`tests/test_db_repositories.py`).

- **Not found.** `get` raises `NotFound(kind, id)`.
- **Revisions.** Mutable records start at revision 1. `update(model, expected_revision)`
  raises `Conflict` and changes nothing when the stored revision differs; otherwise it
  stores the record and returns it with the revision increased by one.
- **`record_check` is not an edit.** `DataSourceRepository.update` writes what a person or
  agent edits (name, address, options, freshness, declared schema) and never the
  `last_checked_at`, `last_probe_token`, `last_error` columns. `record_check` writes only
  those, with a plain UPDATE that leaves the revision alone, so a refresh never makes a
  concurrent edit conflict and an edit never puts back an old refresh outcome.
- **Immutable records.** Operators, snapshots, runs, dashboard versions and report
  versions are only ever added.
- **Operator ids.** `operator_identity(project_id, kind, params, inputs)` is the id.
  Adding an operator that exists returns the stored one.
- **Runs fix snapshots once.** `fix_snapshot` keeps the first snapshot recorded for an
  operator.
- **Events go out after the commit.** Services publish through the request-scoped
  `EventPublisher`, which hands each event to `AfterCommit`; the APP-scoped
  `EventBroadcaster` (Valkey) delivers it once the unit has committed, and it is dropped on
  a rollback. A client that fetches on an event finds what it names; failed work announces
  nothing. `publish` never raises.
- **External failures are `Unavailable`.** An external dependency that could not be
  reached or answered with an error (a data source, the task queue) raises
  `Unavailable` (`core/models/errors.py`): nothing is wrong with the request and retrying
  later may work. The HTTP readers' `SourceUnavailable` is one; the Valkey dispatcher
  turns taskiq's `SendTaskError` into one.

## Sources

Decided in wave 1, shared by the sources, the pipelines and the worker:

- **The source operator is made by `register`.** `SourceService.register` stores the data
  source and its one source operator, whose identity is fixed:
  `operator_identity(project_id, SOURCE, {"data_source_id": "<id>"}, ())`
  (`source_operator_id` in `core/services/sources/service.py`). `add_source_operator`
  computes the same id, so it finds that operator.
- **Source snapshots come only from a refresh.** They belong to the source operator, with
  `parameters_key = ""`: wave 1 fetches each source whole. A refresh writes a snapshot only
  when the content hash changed, and supersedes the previous one.
- **A refresh respects freshness.** `refresh(id)` does nothing while the current snapshot
  is fresh by the source's policy; with a probe policy it fetches only when the probe
  token changed. `refresh(id, force=True)` skips both. A run calls `refresh(id)` for every
  source it fixes, so most runs fetch nothing; a failed refresh keeps the last good
  snapshot current, and widgets on it show `is_stale`.
- **A failed refresh stays recorded.** The failure (`last_error`) is written through
  `SourceCheckLog`, in its own short transaction, before the error is raised on; the
  caller may roll back. A success is recorded in the caller's transaction, with the
  snapshot it wrote.
- **Edits refetch.** A REST or MCP update that changes a source's `address` or `options`
  queues `refresh_source(id, force=True)` after the commit.

## Worker tasks

Named `<module>:<function>`; the dispatcher queues them by name
(`adapters/valkey/tasks.py`) and a test checks the names match what the worker registers.

| Task | When | Does |
| --- | --- | --- |
| `ada.entrypoints.worker.tasks.sources:refresh_source` | Queued by REST, MCP, `seed-demo --refresh`, and for due sources | `SourceService.refresh(id, force)`; a failure is logged, the task ends normally |
| `ada.entrypoints.worker.tasks.sources:refresh_due_sources` | Every minute (scheduler) | Queues `refresh_source` for each source `SourceService.due()` returns |
| `ada.entrypoints.worker.tasks.runs:execute` | Queued by `TaskDispatcher.execute` | `RunService.execute(run, operator)` |
| `ada.entrypoints.worker.tasks.system:record_heartbeat` | Every minute (scheduler) | Proves scheduler, queue and worker work (health) |
| `ada.entrypoints.worker.tasks.alerts:check_alert_rule` | Wave 2 | Not registered yet |

## REST

All routes are under `/api`. Bodies are the domain models' JSON forms; request bodies
reject unknown fields.

| Method and path | Does |
| --- | --- |
| `GET /projects`, `POST /projects {name}` | List; create |
| `GET /projects/{id}`, `PATCH /projects/{id} {name, expected_revision}` | Read; rename |
| `GET /projects/{id}/sources`, `POST /projects/{id}/sources` | List; register (`name, access_kind, address, format`, optional `options, freshness, declared_schema`) |
| `GET /sources/{id}`, `PATCH /sources/{id} {expected_revision, ...}` | Read; update the given fields. A changed address or options queues a forced refresh |
| `POST /sources/{id}/refresh {force?}` | Queue a refresh; answers 202 |
| `GET /projects/{id}/sessions`, `POST /projects/{id}/sessions {title}` | List; create |
| `GET /sessions/{id}`, `PATCH /sessions/{id} {expected_revision, title?, panel_dashboard_id?}` | Read; rename or set the panel dashboard |
| `GET /sessions/{id}/entries` | The session's record, oldest first |
| `POST /sessions/{id}/messages {text}` | Add a message |
| `GET /sessions/{id}/widgets` | The session's widgets |
| `POST /projects/{id}/operators` | Add an operator; the body's `kind` selects source, transform or input |
| `GET /operators/{id}`, `GET /operators/{id}/lineage` | Read; the pipeline, inputs first |
| `POST /projects/{id}/runs`, `GET /runs/{id}` | Start; read |
| `GET /runs/{id}/operators/{operator_id}/rows?limit=` | An operator's output in a run |
| `GET /projects/{id}/widgets`, `POST /projects/{id}/widgets` | Every widget of the project, oldest first; create |
| `GET /widgets/{id}` | Read |
| `GET /widgets/{id}/data?run_id=&limit=` | `WidgetData`; without `run_id` a new run is started |
| `GET /widget-bundles/{type}.html` | A built widget (see Widgets) |
| `GET /projects/{id}/events` | The live stream |

- **Status codes.** 201 for a create, 202 for a queued refresh, 200 otherwise. Errors are
  `{"detail": "..."}` with 404 for `NotFound`, 422 for `Invalid` (and malformed bodies),
  409 for `Conflict`, 503 for `Unavailable`. A 409 adds `expected_revision` and
  `revision`.
- **Writes to mutable records** carry `expected_revision` in the body.
- **Who is acting.** There are no users: requests from the frontend act as
  `Actor(kind="user", name="web")`.

## MCP tools

Tool names are snake case and start with a verb. Tools that create something in a
session take an optional `session_id` and a `note`: one line on why the agent is doing
this, shown in the session. The acting `Actor` is `external_agent` with the client name
the MCP host reported when it connected.

Wave 1: `list_projects`, `create_project`, `register_source`, `list_sources`,
`update_source`, `refresh_source`, `create_session`, `add_source_operator`,
`add_transform`, `get_lineage`, `preview_operator`, `create_widget`,
`list_session_widgets`, and `get_widget_data` for the widget itself (MCP Apps visibility
`app`), besides `system_status`.

Tools return ids and small previews, never whole datasets. A tool that produces a widget
returns the widget and its address in the frontend. The core's errors come back as tool
errors with their message; `Unavailable` adds that it is temporary and to try again later.

### Widget specs

`create_widget` takes a `type` and a `spec` of that type's settings, all optional:

| Type | Spec keys |
| --- | --- |
| `value` | `column` (default: the first measure role, else the first numeric column), `label` (default: the column name), `unit`, `decimals`. Shows the latest period when the output has a time role, else the last row |
| `table` | `columns`: the column names to show, in order (default: all) |
| `line-chart` | `x` (default: the time role's start, else the first date column), `y`: one column (default: the first measure role, else the first numeric column), `series`: a column whose values split the lines |

## Live events

`GET /api/projects/{id}/events` is a server-sent event stream. Each message is

```
event: <EventType value>
data: <the Event as JSON>
```

Payloads carry ids only; the client fetches what it needs. The types are in
`ada/core/models/events.py`. A comment line is sent after 15 quiet seconds to keep the
connection open. Events are broadcast after the unit of work that caused them commits.

| Event | Payload |
| --- | --- |
| `session.created` | `session_id` |
| `session.entry_added` | `session_id`, `entry_id` |
| `widget.created` | `widget_id`, `session_id` if any |
| `run.started`, `run.finished`, `run.failed` | `run_id`, `operator_id`; `error` on failure |
| `source.refreshed`, `source.refresh_failed` | `data_source_id`, `changed`; `error` on failure |

## Widgets

A widget type is a folder `services/widgets/src/widgets/<type>/`, built into one
self-contained file `dist/<type>.html`. `any` is the one bundle that renders every type,
picked by the widget's `type`. A widget never receives data from an agent; it asks the
server for the output of its operator.

- **Where the built files are.** `WIDGETS_DIR` (default: `services/widgets/dist` of the
  checkout; moon sets it; `/app/widgets` in the backend image, which builds them).
  `GET /api/widget-bundles/<type>.html` serves a file that exists there; names other than
  `[a-z0-9][a-z0-9-]*` are 404, so no path leaves the directory.
- **In the frontend.** The frontend loads `<base>/<type>.html#widget=<id>&run=<run>` in
  an iframe, `run` optional, with the base from `VITE_WIDGETS_URL`: the widgets dev server
  in development, `/api/widget-bundles` otherwise. The widget reads
  `GET /api/widgets/{id}` and `GET /api/widgets/{id}/data` on the same origin.
  `WidgetData.output` is the operator's output schema, so the roles (time, measures and
  their bounds) need no third request; `GET /api/operators/{id}` still works.
- **In an MCP host (MCP Apps).** Every bundle is a resource `ui://ada/widgets/<type>.html`
  (`text/html;profile=mcp-app`), and `create_widget` names `ui://ada/widgets/any.html`
  as its UI. With no fragment and a parent frame, the runtime speaks the MCP Apps
  protocol over postMessage: `ui/initialize`, then `ui/notifications/initialized`; it
  takes the widget from the `ui/notifications/tool-result` of `create_widget` and calls
  `get_widget_data` with `tools/call` through the host. No REST is used there.
- **What it must show.** A marker when `is_scenario` is true, and one when `is_stale`
  is true. A simulated or outdated number must never look like a measured, current one.
- **Access to the host.** All of the above goes through `services/widgets/src/lib/host.ts`.

## Frontend routes

| Path | Shows |
| --- | --- |
| `/` | Projects |
| `/projects/{id}` | A project: its sessions, widgets and data sources |
| `/projects/{id}/sessions/{session_id}` | A session's record with its widget cards; `?widget=<id>` scrolls to one. MCP tools return this address for widgets made in a session |
| `/projects/{id}/widgets/{widget_id}` | One widget on its own page; the address of widgets made outside a session |

## Tests

- Backend tests run without services, except those that take the `database_url` or
  `migrated_database_url` fixture (PostgreSQL) or the Valkey fixtures of
  `tests/test_events_valkey.py` and `tests/test_worker_dispatcher.py`. They need
  `moon run root:infra` and are skipped locally when it is not running; with `CI` set
  they fail instead. CI starts both.
- The composition root binds PostgreSQL and Valkey. A test that builds the app, the MCP
  server, the worker or a container passes the in-memory adapters from `tests/memory.py`
  (`MemoryBackground` for events and tasks, `MemoryRepositories` for the repositories)
  unless it means to use the real service.
- `tests/factories.py` builds models with defaults. `tests/fakes.py` has a clock that
  stands still, a source reader that returns what it is told, and an analysis store that
  runs no SQL.
- No test calls an external service. Source readers are tested against recorded
  responses (`tests/recordings`, replayed by `Replay` in `tests/test_sources_examples.py`).
- `tests/test_end_to_end.py` drives the slice over MCP against PostgreSQL, the DuckDB
  store and the recorded NORDCAN answer, with the worker's tasks in an in-memory broker.
- The frontend's API types are generated: `moon run frontend:generate` after the routes
  change, and commit `openapi.json` and `schema.d.ts`.

| Package | Holds | May import |
| --- | --- | --- |
| `ada.core.models` | Domain models | nothing of ours |
| `ada.core.ports` | Outbound ports: what the core needs from the outside | models |
| `ada.core.services.ports` | Inbound ports: the use cases | models |
| `ada.core.services` | The use cases' implementations | models and both kinds of ports |
| `ada.adapters` | Implementations of outbound ports: PostgreSQL, Valkey, DuckDB, HTTP | models, outbound ports |
| `ada.entrypoints` | HTTP, MCP, worker, CLI | models and both kinds of ports, resolved through the container |
| `ada.composition` | Binds every port to its implementation | everything |

Two stores, with different jobs:

- **PostgreSQL** holds definitions: projects, operators, runs, dashboards, reports. Access
  goes through SQLAlchemy; Alembic migrations live in `ada/adapters/db/migrations`.
- **Parquet files queried with DuckDB** hold analysis data. A snapshot is written once and
  never changed, and every process reads the files with its own in-memory DuckDB, so the
  API and the workers do not contend for one database file.

Background work (runs, source refreshes, alert checks) goes through taskiq with Valkey as
the broker. There is exactly one scheduler.

## Known issues, for wave 2

- **Widget frames share the API's origin.** The frontend frames widgets with
  `sandbox="allow-scripts allow-same-origin"` from `/api/widget-bundles`, the API's own
  origin. A sandbox with both flags on the same origin can remove its own sandbox, so a
  widget bundle can do anything the page can: call every route, read the page. The bundles
  are our own code, so this is no hole today, but it must not stay that way once widgets
  render anything less trusted. Options: serve the bundles from a separate origin, or drop
  `allow-same-origin` and hand the widget its data over postMessage, as in an MCP host.
- **The MCP Apps bridge is untested against a real host.** It follows the MCP Apps
  protocol (`ui/initialize`, `ui/notifications/tool-result`, `tools/call`, version
  `2026-01-26`) and is tested against a fake host frame only. Not done: the
  `ui/notifications/tool-input`, `host-context-changed` and teardown messages, size
  reporting to the host, theming from the host context, and a CSP declaration on the
  resources (none is needed while the bundles load nothing). `get_widget_data` is marked
  for the app only, but FastMCP still lists it to every client.
- **`source.refresh_failed` follows the caller's transaction.** The failure record is
  committed at once, but the event goes out only if the caller commits: a widget request
  that fails because its source has no data yet answers 503 and announces nothing.
- **After-commit actions are not retried.** If queueing the refresh that follows a source
  edit fails after the commit, it is logged and lost; the next due refresh, or a manual
  one, fetches the new address.
- **Widget data without a run starts a new run each time.** Runs accumulate; nothing
  prunes them yet.
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

There are no users and no authentication yet: whoever can reach the gateway can use the
API and the MCP endpoint. Do not expose it publicly as it is.

Secrets never go into the repository. `.env` holds only `VERSION`; put local secrets in
`.env.local`, which git ignores.
