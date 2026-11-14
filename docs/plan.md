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

## Wave 2: dashboards, reports, alerts (four agents at once)

Starts from the integrated wave 1. The tables already exist from the foundation.

| # | Workstream | Owns | Builds |
| --- | --- | --- | --- |
| G | Dashboards | `core/services/dashboards/**`, matching router, tools and repository files | Dashboard and DashboardVersion; pinning a session widget; the time-range control; the dashboard panel beside a session |
| H | Reports | `core/services/reports/**`, matching files | Report and ReportVersion with semantic versions; templates with slots; generating a report from a dashboard at a run |
| I | Alerts | `core/services/alerts/**`, matching files | Rule formula tree and its compilation to SQL; check intervals; alert instances per key; the alert feed |
| J | Roles and time | `core/services/schema/**`, widgets that need roles | Role declarations and the build-time schema check; interval periods; pushdown of the time range to sources; a map widget |

G, H and I each add their own repository, router and tool files, so they stay apart.
J touches the pipeline service from wave 1 and must be merged last.

A second integration step follows, as after wave 1.

## Later, not planned here

Agent operators and the recommendation widget; Input operators with simulation bindings;
statistic operators; the in-platform agent; document and browser sources; alert
pipelines; data-quality alerts.

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
Foundation ──▶ A  B  C  D  E  F ──▶ Integration 1 ──▶ G  H  I  J ──▶ Integration 2
```
