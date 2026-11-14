# Contract: wave 4, a better MCP for analysis

Decided with the user after the goal 3 analysis was built through the MCP tools (30 calls,
9 dashboard versions, exploration done outside ADA with curl and pypdf).

Three agents work at the same time, each in its own worktree:

| Agent | Builds | Owns |
| --- | --- | --- |
| MCP | A, B, E, F below | `entrypoints/mcp/tools/{pipelines,dashboards,sources}.py`, the server instructions in `entrypoints/mcp/server.py`, the services behind them (`core/services/pipelines`, `core/services/dashboards`, the refresh path of `core/services/sources`), their REST routes where one exists |
| Documents | D | `adapters/sources/` (a new document reader), the `document` branch of source registration and fetching, the backend dependency `pdfplumber` |
| Widgets | C | `services/widgets` (the new `chart` widget and the table/value options), `core/services/widgets` (spec checks), `entrypoints/mcp/tools/widgets.py`, the frontend's per-type card sizes |

Touch nothing outside your column unless the contract says so; where you must, keep the
change small and say so in your report. Each agent adds only a few focused tests (the suite
was just consolidated: one file per feature, see `docs/contracts.md`, "Tests").

## A. `query_operator`: explore any operator (MCP)

```
query_operator(operator_id, select, where=None, group_by=None, having=None,
               order_by=None, limit=100, run_id=None, snapshot_id=None)
```

- Any operator, sources included. Reads at `run_id`, or one stored `snapshot_id` of a
  materializing operator (a source's or a materialized transform's), or by default a new
  run with no bindings and an open range.
- Each clause is an SQL fragment; window functions are allowed in `select`. They are put
  together as `SELECT {select} FROM input_0 [WHERE] [GROUP BY] [HAVING] [ORDER BY] LIMIT n`
  and checked by the guard transforms already use (one SELECT, nothing else), then run with
  `RunService.query` (or on the snapshot). `limit` at most 500. Nothing is stored.
- Returns `{columns, rows, truncated, run_id, note}` where `note` says, every time: "For your
  own exploration only. Do not show or quote these rows to the person: anything you present
  must come from a transform and a widget, so it can be traced."
- The tool description and the server instructions say the same.

## B. Batches (MCP)

**`build_pipeline(project_id, steps, session_id=None)`**, steps in order, each one of:

```json
{"ref": "s", "register_source": {...same fields as register_source...}}
{"ref": "src", "source_operator": {"data_source_id": "<id or $ref>"}}
{"ref": "slot", "input": {"name": "...", "output": {...}, "default": "<op id or $ref>"}}
{"ref": "t", "transform": {"sql": "...", "inputs": ["$src", "op_..."], "roles": {...}, "materialize": false}}
{"ref": "w", "widget": {"operator": "$t", "type": "...", "title": "...", "spec": {...}}}
```

- Every step may carry `note`; with `session_id` each step gets its session entry, as the
  single tools do.
- `$name` refers to an earlier step's result; plain ids refer to what exists. An unknown or
  later reference is an Invalid naming the step.
- One unit of work: everything is created or nothing is (the first failure names its step
  index and ref). Events go out after the commit, as always.
- Returns `{"refs": {"src": "op_...", "t": "op_...", "w": "<widget id>", "s": "<source id>"}, "widgets": [{"id", "url"}]}`.
- A source registered in the batch is not fetched; its `declared_schema` is enough to check
  the steps after it (as `add_transform` already does). `refresh: true` on a
  `register_source` step queues a refresh after the commit.
- Running the same batch again creates no duplicate operators (identity) and no duplicate
  sources (an existing source with the same project, name and address is reused).

**Dashboards**

- `edit_dashboard` accepts any widget of the dashboard's project in a slot. A widget that is
  not already on this dashboard is copied on the way in (`copied_from`, as `pin_widget`
  does). One call, one version.
- `pin_widget` takes an optional `layout` (`{x, y, w, h}`).
- REST `PUT /dashboards/{id}/slots` gets the same copy-on-add.

## C. Widgets (Widgets)

- **`chart`**, a new widget type rendered with **Vega-Lite** (`vega`, `vega-lite`,
  `vega-embed`, pinned versions, bundled into the single-file widget). `spec` is a
  Vega-Lite spec without `data`: ADA puts the operator's rows in as
  `data: {values: [...]}`. Refused at `create_widget`: `data`, `datasets`, any `url` key
  anywhere, `href` encodings, `usermeta`; the spec must parse with vega-lite's compiler
  (check in the widget at render time; the backend does the structural checks). Expressions
  run with Vega's expression interpreter (no `eval`), so the frame's CSP needs no
  `unsafe-eval`. The widget follows the page theme (light/dark) and the frame's size
  (`width`/`height: "container"`), and marks simulated and outdated data like the others.
  The `create_widget` description names the library and version and gives two short
  examples (a line with a target `rule`, a bar chart).
- **table**: `labels` (`{column: "Header text"}`) and `format` (`{column: "integer" | "number" |
  "percent" | "plain"}` plus optional `decimals`).
- **value**: `compare_to` (a column name or a number, shown as "+1,346 against 11,970") and
  `format`.
- **Fix**: integer columns named `year` (or ending in `_year`) and the time role's columns
  render without thousands separators.
- `line-chart` keeps working unchanged.

## D. PDF documents (Documents)

- `access_kind: "document"` with `format: "pdf"` (add `pdf` to `DataFormat`): the address is a
  PDF URL; fetched over HTTP like a URL source and extracted locally with `pdfplumber`. No
  Context.dev.
- `options.extract`: `"pages"` (default) gives rows `page integer, text text`; `"tables"`
  gives rows `page integer, table integer, row integer, cells json` (the cells of one table
  row, as a JSON array of strings).
- Stored as a snapshot like any source (content-addressed Parquet); probes and freshness as
  for URL sources. A malformed or encrypted PDF is a readable failure on the source
  (`last_error`).
- The output schema is fixed per mode, so the operator's columns are known at registration.

## E. Refresh and wait (MCP)

- `refresh_source(source_id, force=False, wait=False, timeout_seconds=30)`: with `wait`, the
  fetch runs in the call (at most 60 s) and returns `{status: "fetched" | "unchanged" | "failed",
  snapshot: {id, row_count, fetched_at} | null, error: str | null}`; without it, as today.
- REST `POST /sources/{id}/refresh` takes the same `wait`.

## F. Guidance (MCP)

- Server instructions, in a few lines: batch first (`build_pipeline`, `edit_dashboard`),
  explore with `query_operator` (never present its rows), present only through widgets.
- `add_transform` mentions DuckDB's `UNPIVOT` for wide tables (one column per year).

## Later, not in this wave

**Functions**: a project defines functions (a parameterised pipeline with typed inputs), and
a `call` operator applies one to operators; lineage shows the call and the function's
version. Replaces templates and copy-paste of SQL. Planned in `docs/plan.md`.
