# ADA

Agentic data analysis: an agent builds pipelines of operators over data sources, and their
results are shown as widgets on live dashboards and in versioned reports. Everything is
reachable over MCP as well as through the web frontend, so an agent in your own client and
the agent inside the platform work on the same project.

## Layout

| Path | What it is |
| --- | --- |
| `services/backend` | Python: the REST API, the MCP server, the task worker and scheduler |
| `services/frontend` | React single-page app |
| `services/widgets` | Widgets, each built into one self-contained HTML file |
| `services/gateway` | nginx in front of everything: `/api` and `/mcp` to the backend, the rest to the frontend |
| `docker-compose.infra.yml` | PostgreSQL and Valkey |
| `docker-compose.yml` | The full stack |

## Setup

Tool versions are pinned in `mise.toml`.

```sh
mise install            # node, pnpm, python, uv, moon
moon run root:install   # pnpm and uv workspaces
```

## Development

```sh
moon run :dev
```

This starts PostgreSQL and Valkey in Docker, applies migrations, and runs the API, the
worker, the scheduler and the frontend from source with reload.

- Frontend: http://localhost:5173 (Vite forwards `/api` and `/mcp` to the backend)
- API docs: http://localhost:8000/api/docs
- MCP endpoint: http://localhost:8000/mcp

To debug a service in an IDE instead, start only the infrastructure with
`moon run root:infra` and run that service yourself with the environment from
`services/backend/moon.yml`.

| Task | What it does |
| --- | --- |
| `moon run root:infra` / `root:infra-down` | Start or stop PostgreSQL and Valkey |
| `moon run :dev` | Everything from source |
| `moon run :lint :typecheck :format :test` | The checks CI runs |
| `moon run :build` | Build the frontend and the widgets |
| `moon run backend:migrate` | Apply pending migrations |
| `moon run backend:revision -- "<message>"` | Write a migration from the model changes |
| `moon run frontend:generate` | Regenerate the frontend's API types from the backend's schema |
| `moon run widgets:build` | Build the widgets the backend serves (`WIDGETS_DIR`) |

### Demo data

`ada seed-demo` creates the project "Nordic cancer care" with three public sources
(Sotkanet, Statistics Finland, NORDCAN), unless it exists; `--refresh` also queues a fetch
of each for the worker. From source: `cd services/backend && uv run ada seed-demo` with the
environment of `services/backend/moon.yml`; in the full stack:
`docker compose exec backend ada seed-demo --refresh`.

## Running the full stack

```sh
moon run :image     # build all images from the checkout, or
moon run root:pull  # fetch them from ghcr.io

moon run root:up    # http://localhost:8080
moon run root:logs
moon run root:down
```

### Versions

CI publishes every image to `ghcr.io/benni-tec/ada/<service>` with two tags: `latest`, and
`sha-<commit>` for the commit it was built from. `moon run :image` builds the same two
tags locally.

Compose reads the tag for all of them from `VERSION` in `.env`. It is `latest` by default;
`moon run root:pin` sets it to the current commit for a reproducible deploy, and
`moon run root:unpin` sets it back.

## Architecture

The backend is hexagonal. Dependencies point inwards, and `tach` fails the lint when an
import crosses a boundary (`services/backend/tach.toml`).

| Package | Holds | May import |
| --- | --- | --- |
| `ada.core.models` | Domain models | nothing of ours |
| `ada.core.ports` | Outbound ports: what the core needs from the outside | models |
| `ada.core.services.ports` | Inbound ports: the use cases | models |
| `ada.core.services` | The use cases' implementations | models and both kinds of ports |
| `ada.adapters` | Implementations of outbound ports: PostgreSQL, Valkey, DuckDB | models, outbound ports |
| `ada.entrypoints` | HTTP, MCP, worker, CLI | inbound ports, through the container |
| `ada.composition` | Binds every port to its implementation | everything |

Two stores, with different jobs:

- **PostgreSQL** holds definitions: projects, operators, runs, dashboards, reports. Access
  goes through SQLAlchemy; Alembic migrations live in `ada/adapters/db/migrations`.
- **Parquet files queried with DuckDB** hold analysis data. A snapshot is written once and
  never changed, and every process reads the files with its own in-memory DuckDB, so the
  API and the workers do not contend for one database file.

Background work (runs, source refreshes, alert checks) goes through taskiq with Valkey as
the broker. There is exactly one scheduler.

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

There are no users and no authentication yet: whoever can reach the gateway can use the
API and the MCP endpoint. Do not expose it publicly as it is.

Secrets never go into the repository. `.env` holds only `VERSION`; put local secrets in
`.env.local`, which git ignores.
