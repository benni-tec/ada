# Wave 6 contract: custom widgets and session attachments

Read `docs/contracts.md` first. This file only covers what wave 6 adds. After the merge it
gets folded into `docs/contracts.md` and deleted.

Already on main before wave 6 starts:

- **Named widget inputs** (`f30da72`):
  - `Widget.inputs`, `Widget.all_inputs()`, `MAIN_INPUT`.
  - `WidgetData.input`, `GET /widgets/{id}/data?input=` and MCP `get_widget_data(input=)`.
  - `Widget.render_error` (a column; nothing sets it yet).
- **The judges' review port** (`fea6b88`):
  - Models: `core/models/judges.py`.
  - Port: `JudgeService.review` in `core/services/ports/judges.py`.
  - Binding: `UncheckedJudges`. Every verdict is `unchecked`, `passed=False`, `blocking=False`.
  - Another session is building the real judges in parallel (their migration is `0012`). Call only `review`.
- **Migration `0011`** (this commit). Wave 6 writes no other migration. It also holds
  `dashboards.position` and `reports.position` for the sidebar's order (already built on
  main: `reorder` on both services, `PUT /projects/{id}/{dashboards,reports}/order`).
  - `widgets.verdict` (JSONB, nullable).
  - The table `session_attachments`: `id`, `session_id` (cascade), `kind` (≤ 16), `ref` (text), `title` (text, `''`), `actor` (JSONB), `created_at`, unique (`session_id`, `kind`, `ref`).
  - Every non-null `sessions.panel_dashboard_id` is copied into `session_attachments` as a `dashboard` attachment.
  - The `panel_dashboard_id` column stays in the database, unused once wave 6 lands.
  - The rows are `WidgetRow.verdict` and `SessionAttachmentRow` in `adapters/db/tables.py`.

Never touch these: the judges' files beyond calling `review`, migrations, and
`docs/superpowers/plans/2026-11-14-text-widget-and-judges.md`, which is another session's
uncommitted file.

## A. Custom widgets

An agent writes how to draw, never the data. The type is `"custom"`.

### The spec

`spec: {code: str, css?: str, libraries?: ["d3" | "vega-lite"]}`. No other keys are allowed.

`code` is an ES module whose default export draws:

```ts
export default function render(root: HTMLElement, data: Data, ada: Ada):
  void | (() => void) | Promise<void | (() => void)>
// The function it returns (or resolves to) is called before the next render.

type Column = { name: string; type: 'text' | 'integer' | 'number' | 'boolean' | 'date' | 'timestamp' | 'json' }
type Dataset = {
  columns: Column[]
  rows: Record<string, unknown>[]   // one object per row, keyed by column name; dates as ISO strings
  roles: { time: ...; geo: ...; measures: ... }   // the operator's output roles (Schema.roles)
  truncated: boolean                // the input had more than 5,000 rows
}
type Data = {
  main: Dataset                     // the widget's own operator
  inputs: Record<string, Dataset>   // every input by name, "main" included
  run_id: string
  is_scenario: boolean
  is_stale: boolean
}
type Ada = {
  theme: 'light' | 'dark'
  colors: { foreground: string; muted: string; background: string; border: string; accent: string;
            positive: string; negative: string; warning: string; series: string[] }  // series: 8 colours
  size: { width: number; height: number }
  onResize(callback: (size: { width: number; height: number }) => void): void
  format: {
    number(value: number | null, options?: { format?: 'integer' | 'number' | 'percent' | 'plain'; decimals?: number }): string
    date(value: string | null, options?: { grain?: 'day' | 'month' | 'quarter' | 'year' }): string
  }
  libraries: { d3?: typeof import('d3'); vegaEmbed?: typeof import('vega-embed').default }  // only those listed
  error(message: string): void      // report a problem without throwing
}
```

- The number and date formats are the platform's, the same ones the built-in types use (`columns.ts`).
- `render` runs again after a new run or a theme change, on an emptied `root`.
- Resizing does not re-render; the code subscribes with `onResize`.

### Checks (backend, `core/services/widgets/specs.py`)

On create and update, every problem is named at once, in one `Invalid`.

- `code` is required and non-empty. `code` plus `css` is at most 64 KB.
- It must contain `export default`. `libraries` may only name the two listed libraries.
- These are refused anywhere in `code`. The message says comments count too.
  - Network and storage: `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, `importScripts`, `document.cookie`, `localStorage`, `sessionStorage`, `indexedDB`.
  - Loading code: `import(`, static `import` statements (libraries come through `ada.libraries`), `eval`, `Function(` (`new Function` too).
  - Reaching outside the frame: `window.parent`, `window.top`, `parent.`, `top.`, `opener`.
  - Addresses: any `http://` or `https://` literal, except `http://www.w3.org/...` namespaces.
- CSS: `@import` and `url(` with an `http(s)` address are refused.
- **Data written into code.** An array literal with more than 12 number literals is refused, with its line number: "data comes from the widget's inputs, not from its code". The judge covers the subtler cases.

### The judge

On create, and on an update that changes the spec, type or inputs of a custom widget:

1. Start one run (`WIDGET_ACTOR`) and read up to 20 rows of every input. A failed read gives columns only.
2. Call `JudgeService.review(project_id, JudgeKind.WIDGET_CODE, content=code + "\n/* css */\n" + css, JudgeContext(inputs=(JudgeInput(name, columns, rows), ...), note=f"custom widget: {title}"))`.
3. A `blocking` verdict refuses with `Invalid`, listing every finding's message and excerpt. Otherwise the verdict is stored.

- `Widget.verdict: Verdict | None` sits on the model (`None` for the other types) and the repository maps it.
- The other types are never reviewed.

### Render errors

What the frame reports is stored on the widget, so the agent that wrote the code can fix it.

- `WidgetService.report_render(id, error: str | None) -> None`.
  - It stores `render_error`, trimmed to 2,000 characters, only when it changed.
  - It publishes `widget.updated` when it changed. It records no session entry.
- REST: `POST /widgets/{id}/render` with body `{error: string | null}` returns 204. Only the frame calls it.
- An update that changes the spec, type or inputs clears `render_error`.
- MCP `get_widget(session_id, widget_id) -> WidgetView`:
  - Returns the widget with its spec (the code), inputs, `render_error`, `verdict`, and its url.
  - Docstring: check that a custom widget drew, then fix it with `update_widget`.
- **Briefing.** The platform agent's briefing lists the session's widgets that have a `render_error` or a verdict of `fail` or `warn`: one line each, with title, id and the error or findings.
  - Put this in a helper of its own in `core/services/agents/briefing.py`. Workstream B edits the same file.
- `create_widget`'s docstring gains a "custom" entry. This is the agent's documentation, so make it complete and short:
  - the module shape, `data` and `ada` (as above), the checks, the libraries and the judge;
  - one example: d3 bars from `data.main.rows` with `ada.colors.series[0]` and `ada.format.number`.

### Reports keep what they showed

Adding a report version copies every widget the version shows, of every type, and the version's blocks name the copies.

- A copy works as `pin_widget` and dashboards already do:
  - same operator, inputs, type, spec, title and note;
  - `copied_from` set to the original (or the original's `copied_from`);
  - no session.
- A frozen report keeps its code and spec even when the original is changed with `update_widget`.
- This covers `add_report_version`, `generate_report_from_dashboard` and templates.

### Widgets package (`services/widgets`)

- A new type folder `src/widgets/custom/` builds `dist/custom.html`. The `any` bundle handles `custom` too.
- **The host frame** (`custom.html`, on ADA's origin):
  - Reads the widget and every input's data for the same run through the existing runtime. Add `input=`; `limit=5000`.
  - Creates a child `<iframe sandbox="allow-scripts">` (no `allow-same-origin`), whose `srcdoc` carries:
    - the CSP `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob:; font-src data:">`;
    - the CSS;
    - the listed libraries inlined. Pin d3 7.9.0; for vega-lite use the chart widget's pinned vega / vega-lite / vega-embed.
- **The child frame** has no network and no ADA origin.
  - It receives `{code, data, theme, colors, size}` by `postMessage`.
  - It imports the code from a `blob:` module URL and calls `render`.
  - It reports `{type: "rendered"}` or `{type: "error", message}`: from a throw, a rejected promise, `window.onerror`, `unhandledrejection` or `ada.error`.
  - The host checks that messages come from its own child (`event.source`).
- **Errors.** The host shows the error in the frame: "This widget could not be drawn: <message>".
  - In the ADA frontend, it calls `POST /api/widgets/{id}/render` only when the result differs from the widget's `render_error`. A drawn widget with a stored error sends `{error: null}`.
  - Inside an MCP Apps host it never posts, since there is no REST there.
- **MCP Apps.** Draw if the host allows the nested frame. If the child has not said it is ready within 3 s, show "Open in ADA to see this widget" with the widget's url.
- Scenario and stale flags work as for every type.
- Tests:
  - The checks are backend tests.
  - A widget test draws a small module in jsdom, as far as jsdom allows, and shows a thrown error.

### Frontend (A's part)

- **The card** (`components/widget-card.tsx`):
  - The type badge says "custom".
  - A `render_error` shows as one destructive line under the frame.
  - Verdict findings of `warn` or `fail` show as a yellow warning icon in the footer, with the findings in its tooltip.
  - An `unchecked` verdict shows nothing.
- **The pipeline dialog** (`components/pipeline/*`): for a custom widget, a "Code" tab shows the code and CSS read-only in a monospace block, and the inputs by name with their operators.

### What A owns

- **Backend:**
  - `core/models/widgets.py`, `core/services/widgets/*`, `core/services/ports/widgets.py`;
  - `core/services/reports/*` (the copies);
  - the widget mapping in `adapters/db/workspace_repositories.py`;
  - `entrypoints/mcp/tools/widgets.py`, `entrypoints/http/routers/widgets.py`;
  - the render-error helper in `core/services/agents/briefing.py`.
- **Widgets:** all of `services/widgets`.
- **Frontend:** `widget-card*`, `components/pipeline/*`.
- **Docs:** none; the integrator writes them.

A is split between two agents:

| Agent | Takes |
| --- | --- |
| **A1, backend** | Everything backend above |
| **A2, widgets and frontend** | The widgets package and A's frontend part. It works against this contract. It may hand-edit `services/frontend/src/lib/api/schema.d.ts` and `openapi.json` to add `verdict`, and `services/widgets` types; the integrator regenerates them. |

## B. Session attachments (backend)

### Models (`core/models/attachments.py`, new)

```python
class AttachmentKind(StrEnum):
    DASHBOARD = "dashboard"
    REPORT = "report"          # ref: a report *version* id (frozen)
    ALERT_RULE = "alert_rule"
    SOURCE = "source"
    OPERATOR = "operator"      # a pipeline, by its operator id
    SESSION = "session"        # another session of the project
    WIDGET = "widget"          # a widget from elsewhere
    WEB_PAGE = "web_page"      # ref: an http(s) URL, at most 2,048 characters

class Attachment(DomainModel):
    id: Id
    session_id: Id
    kind: AttachmentKind
    ref: str
    title: str                 # the thing's name when attached; a page's given title or its host
    actor: Actor
    created_at: datetime
```

### Service

`AttachmentService` (`core/services/ports/attachments.py`), with a repository port and SQL and memory repositories:

- `attach(session_id, kind, ref, actor, title=None) -> Attachment`.
  - Checks that the thing exists and belongs to the session's project. A web page's URL is checked instead.
  - For `report`, `ref` may be a report id, which resolves to its latest version.
  - Idempotent: attaching again returns the existing attachment.
  - Publishes `session.attachment_added` with `{session_id, attachment}`.
- `detach(session_id, attachment_id, actor) -> None` publishes `session.attachment_removed`.
- `list(session_id) -> Sequence[Attachment]`, oldest first.

`Session.panel_dashboard_id` leaves the domain model and the API; the column stays, unused.

- Everything that set or read it now attaches or lists: `show_dashboard_in_session`, the sessions REST route, the briefing, and the seed.
- The dashboard's agent session (`dashboard_agent_session`) attaches its dashboard.

### REST

- `GET /sessions/{id}/attachments`
- `POST /sessions/{id}/attachments` with body `{kind, ref, title?}` returns 201 and the Attachment.
- `DELETE /sessions/{id}/attachments/{attachment_id}` returns 204.
- Errors: unknown thing 404; another project or a bad URL 422.

### MCP

- `attach_to_session(session_id, kind, ref, title=None)` and `detach_from_session(session_id, attachment_id)`. Their docstrings say what each kind shows the person.
- `show_dashboard_in_session` is removed; `attach_to_session` replaces it. Check the agent toolbox and tests that name it.
- A dashboard or report created through MCP is attached to the calling session:
  - `create_dashboard`;
  - `create_report`, `generate_report_from_dashboard` and `add_report_version` attach the new version (replacing that report's earlier version attachment).

### Briefing

The session's attachments, one line each: kind, title, ref.

- An alert rule adds its count of active alerts.
- A report version adds its run.

This replaces the "dashboard shown beside the session" line. Keep it in a helper of its own: A1 adds a helper to the same file.

### Alerts in the session

When an alert of a rule attached to a session starts or ends, the alert service adds a session entry to every such session, in the same unit of work.

- The entry has `EntryKind.ALERT` (new), `ref` the alert id, and the text `"<rule name>: <key> started"` or `"... ended"`. The actor is the system.
- The repository needs `sessions_with(kind, ref)`.

### What B owns

- **New files:** `core/models/attachments.py`; the attachments service, port and repositories.
- **Edits:** `core/models/sessions.py` (`EntryKind.ALERT`, no `panel_dashboard_id`), `core/models/events.py`, `core/services/sessions/*`, `core/services/alerts/*`, `core/services/dashboards/*` (only if attaching needs it), `core/services/agents/briefing.py` (the attachments helper), the composition providers.
- **Entrypoints:** `entrypoints/mcp/tools/{sessions,dashboards,reports}.py`, a new `entrypoints/mcp/tools/attachments.py`, `entrypoints/http/routers/sessions.py` (or a new router), `entrypoints/cli/seed.py`.
- **Tests:** backend tests.

## C. Session attachments (frontend)

The right half of a session page shows the session's attachments as tabs.

- **The tab bar** is styled like today's dashboard panel header: black with white text in light mode, white with black text in dark mode.
  - One tab per attachment: a kind icon, the title (truncated, full in a tooltip) and an × that detaches.
  - An "Attach" button opens a searchable chooser of the project's dashboards, reports, alert rules, sources, pipelines, sessions and widgets, plus a URL field for a web page.
  - One view at a time. The last tab picked is remembered per session in `localStorage`, guarded with try/catch.
  - With no attachments the right half shows a short empty state with the Attach button.
- **One view per kind**, reusing components where they exist:
  - **dashboard:** today's dashboard panel.
  - **report:** the report version, frozen at its run.
  - **alert rule:** the rule and its alerts (the nested tables from `components/alerts`).
  - **source:** its provenance, freshness and a rows preview.
  - **operator:** the pipeline graph and a rows preview.
  - **session:** the other session's record, read-only.
  - **widget:** the widget card at the session's run.
  - **web page:** title, URL, an "Open" link (new tab) and nothing framed, since most sites refuse framing.
- **Live updates.** `session.attachment_added` and `session.attachment_removed` refresh the list.
  - An attachment added by an agent becomes the open tab.
  - `alert` entries (`EntryKind.ALERT`) show in the session record, coloured by the rule's severity like the alerts page.
- **Removing the panel dashboard.** Everything that read or set `panel_dashboard_id` now reads or attaches through the attachments API: the session route, `lib/api/dashboards.ts`, `requests.ts`, `dev/mock-agent.ts`, the project overview, and the test fixtures.
- **Types.** C works against this contract. It writes the attachment types and queries in `src/lib/api/attachments.ts`, and may hand-edit `schema.d.ts` and `openapi.json`; the integrator regenerates them.
- **What C owns:**
  - the session route `routes/projects/$projectId/sessions/$sessionId.tsx`;
  - `components/dashboards/dashboard-panel.tsx`, a new `components/attachments/*`, `session-record.tsx` (alert entries);
  - `lib/api/*` (attachments; panel removal), the project overview route, `dev/mock-agent.ts`;
  - frontend tests.

## Every agent

- **Start.** First run `git merge --ff-only <the wave 6 base commit given in your prompt>` in your worktree.
- **Environment:**
  - Run `uv sync --all-packages --all-groups` from the worktree root, never inside `services/backend`. Run `pnpm install` at the root.
  - Postgres (5434) and Valkey (6380) are running in docker.
- **Before you finish:**
  - Run `CI=1 mise exec -- moon run :lint :format :typecheck :test` and make it pass.
  - Commit on your worktree branch, adding paths explicitly.
  - Never push. Never edit `docs/`.
- **Keep the tests few and fast.** Extend the existing feature files (`test_api.py`, `test_pipelines.py`, ...) rather than adding many new ones.
- **Report:** what you built, what you left out, and anything that touches another workstream.
