# Implementation plan

How to build the first working slice of the spec with several agents working at once.
The spec is the design document; step F0 copies it into `docs/spec.md` so every agent
reads the same text.

## Target of this plan

One vertical slice, usable over MCP and visible in the frontend:

> In a session, an agent registers a data source, loads it, transforms it with SQL, and
> creates a widget. The widget shows data it fetched itself by operator id. A person sees
> the session update live in the browser.

A second wave adds dashboards, reports and alerts on top. Everything else in the spec
(agent operators, simulation bindings, statistics, the in-platform agent, document and
browser sources) is listed under "Later" and is not planned in detail here.

## Why there is a foundation step first

Agents working at the same time must not edit the same files, and they need fixed
contracts to code against. Five places in the scaffold would otherwise be edited by
everyone:

| Shared place | Problem | What the foundation does |
| --- | --- | --- |
| `ada/composition.py` | Every feature binds its ports here | Split into one provider module per feature, discovered automatically |
| `entrypoints/http/app.py`, `entrypoints/mcp/server.py`, `entrypoints/worker/tasks.py` | Each holds a hand-written list of modules | Discover router, tool and task modules by package, so a feature adds a file |
| Alembic migrations | Two agents writing revisions create two heads | The foundation writes all tables of both waves in one revision; no other workstream writes migrations |
| `ada/core/models` and the ports | Everyone depends on these shapes | Written once, then frozen for the wave |
| Frontend API types | Hand-written types drift from the backend | Generated from the OpenAPI schema |

`tach.toml` works at package level, so new files inside an existing package need no
change to it.

## Foundation (done)

Ran alone on `main`. Everything after it branches from its result. What it fixed is
written down in `docs/contracts.md`, which every workstream reads first.

- **F0. Spec in the repo.** Export the design document to `docs/spec.md`.
- **F1. Core models.** Project, DataSource, Session, Operator and its six kinds, Schema
  with roles, Run, Snapshot, Widget, Dashboard, DashboardVersion, Report, ReportVersion,
  Template, AlertRule, Alert. Include operator identity (hash of kind, parameters and
  input identities) and the revision field on mutable models.
- **F2. Ports.** Outbound: one repository port per aggregate, `AnalysisStore`
  (write snapshot, describe query, run query, read rows), `SourceReader` per access kind,
  `EventPublisher`, `Clock`. Inbound: one service port per use-case group
  (projects, sources, sessions, pipelines, runs, widgets, dashboards, reports, alerts).
- **F3. Tables and the single migration** for every model above, with JSON columns for
  specs and SQLAlchemy's version counter on the mutable tables.
- **F4. Discovery.** Routers, MCP tool modules, worker task modules and dishka providers
  are found by package scan.
- **F5. Fakes.** In-memory repositories, event bus and task dispatcher in
  `ada/adapters/memory`, bound by default; test-only fakes for the clock, source readers
  and the analysis store in `tests/fakes.py`. Ports nobody has implemented are bound to
  stand-ins, so the application starts in every branch.
- **F6. Typed client.** A task that writes the OpenAPI schema and generates the
  TypeScript client into `services/frontend/src/lib/api`.
- **F7. Contract notes.** `docs/contracts.md`: the widget protocol (how a widget asks
  for its operator's data), the event names on the live stream, and the error shape.

Done when: all checks pass, the migration applies to an empty database, and every port
has a fake.

## Wave 1: the slice (six agents at once) (done)

Each agent works in its own git worktree on its own branch and owns the paths listed.
Nobody edits the frozen contracts; a needed change is reported back, not made.

| # | Workstream | Owns | Builds | Tests against |
| --- | --- | --- | --- | --- |
| A | Persistence | `ada/adapters/db/**` except migrations | Repositories for Project, DataSource, Session, Operator, Run, Snapshot, Widget; optimistic locking on mutable rows | Real PostgreSQL from the infra compose |
| B | Analysis engine | `ada/adapters/duckdb/**`, `ada/core/services/pipelines/**` | Parquet snapshot store; schema derivation by describing a query; planning a run: reuse by identity, materializing versus pass-through, fusing pass-through chains into one query | DuckDB directly; repository fakes |
| C | Sources | `ada/adapters/sources/**`, `ada/core/services/sources/**` | URL and request source readers; freshness policy and probe; three registered examples as fixtures (Sotkanet, Statistics Finland, NORDCAN) with recorded responses | Recorded HTTP responses, no live calls in tests |
| D | Entrypoints | `ada/entrypoints/http/routers/**`, `ada/entrypoints/mcp/tools/**`, `ada/core/services/{projects,sessions,widgets}/**` | REST and MCP for projects, sessions, sources, operators, runs and widgets; revision checks on writes; the note and client name recorded on widgets | Service and repository fakes |
| E | Worker and live updates | `ada/entrypoints/worker/tasks/**`, `ada/adapters/valkey/**`, `ada/entrypoints/http/routers/events.py` | Tasks to execute a run and refresh a source; publish events to Valkey; the server-sent event endpoint | Fakes; Valkey from the infra compose |
| F | Frontend and widgets | `services/frontend/src/**`, `services/widgets/src/**` | Project list, session view with widget cards and the external-agent header, live updates from the event stream; widget runtime that fetches by operator id; value, table and line-chart widgets | Generated client with mocked responses |

Reasons for these cuts:

- **A, B and C never meet.** Each implements different ports behind the same core.
- **D and E share the services but not files.** D owns the request-driven services, E the
  background ones; both call ports only.
- **F is one agent, not two.** The widget protocol crosses the frontend and the widgets
  project, and splitting it would put its two halves in different heads.
- **B is the largest.** If it runs long, its schema derivation can be handed to a
  seventh agent, since it only needs DuckDB.

### Integration (one agent, after wave 1) (done)

Merges the six branches, binds the real adapters in the provider modules, serves the
widget bundles from the backend as MCP App resources, and adds an end-to-end test that
drives the slice over MCP against the compose stack. This is the only step that edits
across workstreams.

Besides the merge it made events and after-commit work transactional, added `Unavailable`
(503), kept failed refresh records apart from the caller's transaction, refetched sources
on edits, filled the contract gaps the frontend found, moved the frontend onto the
generated types, served the widgets over REST and as MCP Apps, and added `ada seed-demo`.
`docs/contracts.md` describes the result and lists the known issues wave 2 starts from.

## Wave 2: dashboards, reports, alerts (four agents at once) (done)

Starts from the integrated wave 1. The tables already exist from the foundation.

| # | Workstream | Owns | Builds |
| --- | --- | --- | --- |
| G | Dashboards | `core/services/dashboards/**`, matching router, tools and repository files | Dashboard and DashboardVersion; pinning a session widget; the time-range control; the dashboard panel beside a session |
| H | Reports | `core/services/reports/**`, matching files | Report and ReportVersion with semantic versions; templates with slots; generating a report from a dashboard at a run |
| I | Alerts | `core/services/alerts/**`, matching files | Rule formula tree and its compilation to SQL; check intervals; alert instances per key; the alert feed |
| J | Roles and time | `core/services/schema/**`, widgets that need roles | Role declarations and the build-time schema check; interval periods; pushdown of the time range to sources; a map widget |

G, H and I each add their own repository, router and tool files, so they stay apart.
J touches the pipeline service from wave 1 and must be merged last.

### Integration 2 (one agent, after wave 2) (done)

Merged G, H, I and J in that order and regenerated the API types and route tree. Besides
the merge it:

- unfroze what the workstreams asked for: `ReportService.sources` and `ReportSource`;
  `AlertService.update_rule` for every field, with `Change[T]` telling "unchanged" from
  "clear"; `Alert.condition_operator_id` and `Alert.pipeline_run_id` (migration `0002`);
- joined the frontend pieces: alert badges and "Generate report" on the dashboard page,
  the report form on the generated client, dashboards that reload their frames once, maps
  in the `any` bundle;
- let the tool-name and composition tests follow wave 2 (the alert check is
  `check_alert_rule`) and documented maps and the interval guard in the MCP tools;
- fixed a race found in the browser: two widgets reading one run both fetched a missing
  period, and the second insert failed; `SourceLocks` now serializes fetches of a source;
- extended `tests/test_end_to_end.py` with the wave 2 slice and `ada seed-demo` with a
  ready demo (map, dashboard, report, alert rule, line chart);
- folded the four wave 2 contract files into `docs/contracts.md`, with the known issues
  the next wave starts from.

## Pipeline view (done)

One agent: a footer on every widget card with the one-line pipeline summary on the left
and icon actions on the right (add to dashboard; on dashboards, go to the session the
widget came from, disabled when it has none); a dialog with the operator tree as a graph,
the selected operator's details, and a preview of its rows in the card's run. Sessions
and widget pages show one run per view, like dashboards.

## Wave 3: the agent in the platform, and the workspace (two agents at once) (done)

Decided with the user:

- **Models.** Providers and models are configured in `llms.yml`, git-ignored, its path
  from `ADA_LLMS_CONFIG` (default `./llms.yml`); `llms.example.yml` is committed. Keys
  are referenced by environment variable name, never written into the file. Most partner
  providers speak the OpenAI chat API; Gemini may also be used natively.
- **Agent runtime.** pydantic-ai, run as a worker task when a message is posted. It uses
  our own MCP tools in-process, so it can do exactly what an external agent can, recorded
  as the agent with its model's name.
- **Reasoning steps.** Each agent turn is stored and streamed as parts (reasoning, tool
  call with arguments and result, sources, text), rendered with the shadcn Trace
  component. Token deltas are the one documented exception to "events carry ids only".
- **Chat.** A chat interface instead of the plain text box. Messages can carry context
  chips: a pipeline, a dashboard, a slot.
- **Add widget.** Widgets stay agent-made. "Add widget" opens a dropdown of the project's
  pipelines (operators with no successor) and hands the chosen one to the chat as a
  chip; the person says what to show. On a dashboard the chip also names the dashboard
  and slot.
- **Dashboard agent panel.** A session linked to the dashboard, so every agent step lands
  in a session.
- **Layout.** shadcn throughout. A side navigation with the project in the header and its
  groups (sessions, dashboards, reports, alerts, data sources). No breadcrumbs: each page
  shows its type (label and icon) above its title. Rename is a pencil icon. Pages use the
  full width.
- **Session with a dashboard beside it.** Half and half; the dashboard half has a black
  header saying "Dashboard" and its name, with an × to detach it.
- **Full-size widgets** open in a modal over the page (`?open=<widget id>`), so closing
  returns to where you were; the standalone widget page remains only for direct links.
- **Dashboard editing.** Drag to move and resize on the 12-column grid; maps keep their
  aspect ratio, other types resize freely. A save on drop adds a dashboard version.
- **Slots** are just places: any widget can go in any slot; names are optional labels.
- **Pinning copies** the widget (`copied_from` points at the original), so a copy can be
  changed alone; "go to the session it came from" follows `copied_from`.

| Agent | Builds |
| --- | --- |
| Backend | `llms.yml` loading; the pydantic-ai agent task; turns as parts, stored and streamed; messages with context; dashboard agent sessions; the pipelines list (route and MCP tool); copy on pin with `copied_from` (migration); layout saves |
| Frontend | shadcn; side navigation and full-width layout; type labels and rename icons; chat with Trace and context chips; "Add widget"; dashboard agent panel; the half-width dashboard beside a session; widget modal; drag and resize |

### Integration 3 (done)

Merged both; regenerated the typed client and replaced the frontend's temporary agent
types with it; made alert rules stop being operators (the condition is kept on the alert
as SQL, migration `0004`), so the pipelines list is plain again; explained in the grid why a narrow dashboard has no handles; folded the
wave 3 contracts into `docs/contracts.md`.

## Bottom-up invalidation of definitions (proposed, after wave 3)

A source's definition (address, options, declared schema) becomes part of its operator's
identity; operators get a `superseded_by` pointer; a definition change rebases everything
downstream, marking operators broken where they no longer fit; live views follow the
newest operator, report versions stay on theirs; schema drift found at refresh is
recorded and flagged, not rebased automatically.

## Test consolidation (last)

Merge test files that test the same thing (`test_http` with `test_api_http`, `test_mcp`
with `test_api_mcp`, the worker, transaction and composition files); drop
`test_memory_repositories.py`, which `test_db_repositories.py` covers for both
implementations; one set of service fakes in `tests/fakes.py`; a shorter long-chain test;
markers for the PostgreSQL and Valkey tests; parallel runs with `pytest-xdist`. No change
in behaviour.

Frontend and widgets: done. Frontend 18 files, 132 tests, 33 s on a quiet machine → 12 files, 46 tests, 4 s (route files no longer load the routes lazily inside their first test); widgets 6 files, 33 tests → 5 files, 17 tests.

## Later, not planned here

Agent operators and the recommendation widget; Input operators with simulation bindings;
statistic operators; document and browser sources; alert pipelines; data-quality alerts.

## Running the agents

- One agent per workstream, each started with: its row of the table, `docs/spec.md`,
  `docs/contracts.md`, the paths it owns, and the instruction to change nothing else.
- Every agent finishes by running `moon run :lint :format :typecheck :test` and reporting
  what it built, what it could not, and any contract it found wrong.
- No agent adds a migration, edits `tach.toml` or changes a model or port. Those requests
  go to the integration step.
- No agent calls an external API in tests or spends credits on a paid service.

## Order

```
Foundation ──▶ A  B  C  D  E  F ──▶ Integration 1 ──▶ G  H  I  J ──▶ Integration 2 (all done)
──▶ Pipeline view ──▶ Wave 3 (backend, frontend) ──▶ Integration 3 (all done)
──▶ Bottom-up invalidation (proposed) ──▶ Test consolidation
```
