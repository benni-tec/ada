# Contracts

What the workstreams of `docs/plan.md` agree on. These are fixed for a wave: if one
turns out wrong, report it instead of changing it, so everyone changes together.

The spec (`docs/spec.md`) says what the system does and why. This file says where things
live and how the pieces talk.

## Frozen code

Do not edit these; build against them.

| Path | What it is |
| --- | --- |
| `ada/core/models/**` | The domain models |
| `ada/core/ports/**` | Outbound ports: repositories, analysis store, source readers, events, tasks, clock |
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

| Provider module | Ports | Today | Replaced by |
| --- | --- | --- | --- |
| `infrastructure.py` | Settings, database engine and session, Valkey client, `Clock` | Real | nobody |
| `system.py` | `Database`, `TaskQueue`, `SystemStatusService` | Real | nobody |
| `repositories.py` | All twelve repositories | In memory | Persistence (A) |
| `analysis.py` | `AnalysisStore`, `PipelineService`, `RunService` | Store real but partial; services stand-ins | Analysis engine (B) |
| `sources.py` | `SourceReaders`, `SourceService` | Stand-ins | Sources (C) |
| `workspace.py` | `ProjectService`, `SessionService`, `WidgetService` | Stand-ins | Entrypoints (D) |
| `background.py` | `EventPublisher`, `EventStream`, `TaskDispatcher` | In memory | Worker and live updates (E) |
| `dashboards.py`, `reports.py`, `alerts.py` | Their services | Stand-ins | Wave 2 (G, H, I) |

Services are bound at `Scope.REQUEST`; whatever holds a connection or shared state at
`Scope.APP`.

## Behaviour every implementation of a port must share

The in-memory repositories (`ada/adapters/memory/repositories.py`) are the reference, and
`tests/test_memory_repositories.py` states the expectations. The database repositories
must pass the same ones.

- **Not found.** `get` raises `NotFound(kind, id)`.
- **Revisions.** Mutable records start at revision 1. `update(model, expected_revision)`
  raises `Conflict` and changes nothing when the stored revision differs; otherwise it
  stores the record and returns it with the revision increased by one.
- **Immutable records.** Operators, snapshots, runs, dashboard versions and report
  versions are only ever added.
- **Operator ids.** `operator_identity(project_id, kind, params, inputs)` is the id.
  Adding an operator that exists returns the stored one.
- **Runs fix snapshots once.** `fix_snapshot` keeps the first snapshot recorded for an
  operator.
- **Transactions.** One per request: commit on success, roll back on an exception.
- **Events never fail the work.** `EventPublisher.publish` does not raise.

## REST

All routes are under `/api`. Bodies are the domain models' JSON forms.

| Method and path | Does |
| --- | --- |
| `GET /projects`, `POST /projects` | List; create (`name`) |
| `GET /projects/{id}`, `PATCH /projects/{id}` | Read; rename |
| `GET /projects/{id}/sources`, `POST /projects/{id}/sources` | List; register |
| `GET /sources/{id}`, `PATCH /sources/{id}` | Read; update |
| `POST /sources/{id}/refresh` | Queue a refresh; answers 202 |
| `GET /projects/{id}/sessions`, `POST /projects/{id}/sessions` | List; create |
| `GET /sessions/{id}`, `PATCH /sessions/{id}` | Read; rename or set the panel dashboard |
| `GET /sessions/{id}/entries` | The session's record, oldest first |
| `POST /sessions/{id}/messages` | Add a message |
| `GET /sessions/{id}/widgets` | The session's widgets |
| `POST /projects/{id}/operators` | Add an operator; the body's `kind` selects source, transform or input |
| `GET /operators/{id}`, `GET /operators/{id}/lineage` | Read; the pipeline, inputs first |
| `POST /projects/{id}/runs`, `GET /runs/{id}` | Start; read |
| `GET /runs/{id}/operators/{operator_id}/rows?limit=` | An operator's output in a run |
| `POST /projects/{id}/widgets`, `GET /widgets/{id}` | Create; read |
| `GET /widgets/{id}/data?run_id=&limit=` | `WidgetData`; without `run_id` a new run is started |
| `GET /projects/{id}/events` | The live stream |

- **Writes to mutable records** carry `expected_revision` in the body.
- **Errors** are `{"detail": "..."}` with 404 for `NotFound`, 422 for `Invalid` and 409
  for `Conflict`. A 409 adds `expected_revision` and `revision`. The handlers are
  installed already (`ada/entrypoints/http/errors.py`).
- **Who is acting.** There are no users: requests from the frontend act as
  `Actor(kind="user", name="web")`.

## MCP tools

Tool names are snake case and start with a verb. Tools that create something in a
session take an optional `session_id` and a `note`: one line on why the agent is doing
this, shown in the session. The acting `Actor` is `external_agent` with the client name
the MCP host reported when it connected.

Wave 1: `list_projects`, `create_project`, `register_source`, `list_sources`,
`refresh_source`, `create_session`, `add_source_operator`, `add_transform`,
`get_lineage`, `preview_operator`, `create_widget`, `list_session_widgets`.

Tools return ids and small previews, never whole datasets. A tool that produces a widget
returns the widget and its address in the frontend.

## Live events

`GET /api/projects/{id}/events` is a server-sent event stream. Each message is

```
event: <EventType value>
data: <the Event as JSON>
```

Payloads carry ids only; the client fetches what it needs. The types are in
`ada/core/models/events.py`. A comment line is sent every 15 seconds to keep the
connection open.

| Event | Payload |
| --- | --- |
| `session.entry_added` | `session_id`, `entry_id` |
| `widget.created` | `widget_id`, `session_id` if any |
| `run.started`, `run.finished`, `run.failed` | `run_id`, `operator_id`; `error` on failure |
| `source.refreshed`, `source.refresh_failed` | `data_source_id`, `changed`; `error` on failure |

## Widgets

A widget type is a folder `services/widgets/src/widgets/<type>/`, built into one
self-contained file `dist/<type>.html`. A widget never receives data from an agent; it
asks the server for the output of its operator.

- **How a widget learns what to show.** From its URL fragment:
  `#widget=<widget id>&run=<run id>`, where `run` is optional.
- **How it gets data.** `GET /api/widgets/{id}/data`, same origin. It renders the
  `spec` of its `Widget` (`GET /api/widgets/{id}`) against the columns it receives.
- **What it must show.** A marker when `is_scenario` is true, and one when `is_stale`
  is true. A simulated or outdated number must never look like a measured, current one.
- **Where the frontend loads it from.** `<base>/<type>.html`, with the base taken from
  `VITE_WIDGETS_URL`: the widgets dev server in development, and
  `/api/widget-bundles` once the backend serves the built files.
- **Access to the host.** All of the above goes through `services/widgets/src/lib/host.ts`,
  so that running inside an MCP host, where data comes through tool calls instead of
  REST, changes one file.

## Tests

- Backend tests run without services, except those that take the `database_url` or
  `migrated_database_url` fixture; they need the PostgreSQL of `moon run root:infra` and
  are skipped locally when it is not running.
- `tests/factories.py` builds models with defaults. `tests/fakes.py` has a clock that
  stands still, a source reader that returns what it is told, and an analysis store that
  runs no SQL.
- No test calls an external service. Source readers are tested against recorded
  responses.
- The frontend's API types are generated: `moon run frontend:generate` after the routes
  change.
