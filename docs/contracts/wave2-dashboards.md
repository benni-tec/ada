# Wave 2, workstream G: dashboards

What workstream G defines. Integration folds it into `docs/contracts.md`.

A dashboard is a live view of a project's widgets. Its content lives in immutable
versions; the `Dashboard` record points at the current one and carries the revision.

## Behaviour of `DashboardService`

Implemented in `core/services/dashboards/service.py`, bound in
`composition/providers/dashboards.py`.

- **Every edit adds a version.** `edit` and `pin_widget` build the new slot list, add a
  `DashboardVersion` (`number` is the previous number plus one, starting at 1; the
  template id carries over) and move `current_version_id`. `set_default_time_range` adds no
  version.
- **The pointer is the revision-checked write.** The dashboard row is updated first with
  `expected_revision`, so a stale caller gets `Conflict` before a version exists. The
  dashboard's revision increases by one on every edit, pin and time range change; a client
  always sends the revision it last read, whichever of the three it is doing.
- **Slot rules.** Names are trimmed, not blank and unique within a version (`Invalid`
  otherwise). A slot's `widget_id` must exist (`NotFound`) and be in the dashboard's
  project (`Invalid`). The same widget may sit in several slots.
- **Pinning.** `pin_widget(id, widget_id, slot, ...)` puts the widget in the slot of that
  name, keeping its layout, or appends a new slot with the default layout. The widget is
  referenced, never copied.
- **Time range.** `start` after `end` is `Invalid`; either end may be open.
- **Create and list** check the project (`NotFound`). A new dashboard has no version:
  `current` returns `None`.

### Layout

A slot's `layout` is `{x, y, w, h}` on a 12-column grid: `x` is the starting column
(0 to 11), `y` the starting row, `w` and `h` the columns and rows spanned. Rows have no
fixed height; the frontend sizes a card to its widget. On every edit the service completes
and validates each layout (`core/services/dashboards/layout.py`), so stored versions always
have all four keys:

- **Defaults.** A slot without a layout, or with keys left out, takes `w = 6`, `h = 4` and
  a position after the previous slot of the same edit: beside it when 6 more columns fit
  in its row, otherwise at `x = 0` on the row below everything placed so far. The first
  slot is at `{x: 0, y: 0}`.
- **Invalid** (`Invalid`, 422): keys other than `x y w h`; values that are not whole
  numbers (booleans included); `x` or `y` negative; `w` or `h` under 1; `x + w` over 12.
  Overlap is not checked.

## Events

`dashboard.changed`, payload `{dashboard_id, version_id}`, published through the
transactional `EventPublisher` (after the commit, dropped on a rollback), by:

| Cause | `version_id` |
| --- | --- |
| A new dashboard | `null` |
| `edit`, `pin_widget` | the new version |
| `set_default_time_range` | the current version, or `null` before the first edit |

The frontend refetches the dashboard, its versions and the project's dashboard list.

## REST

All under `/api`; bodies reject unknown fields; writes carry `expected_revision` and
answer 409 with both revisions on a mismatch.

| Method and path | Body | Answers |
| --- | --- | --- |
| `GET /projects/{id}/dashboards` | | 200, `Dashboard[]`, oldest first |
| `POST /projects/{id}/dashboards` | `{name}` | 201, `Dashboard` |
| `GET /dashboards/{id}` | | 200, `DashboardView` |
| `PATCH /dashboards/{id}` | `{default_time_range, expected_revision}` | 200, `DashboardView` |
| `PUT /dashboards/{id}/slots` | `{slots: Slot[], expected_revision}` | 200, `DashboardView`; adds a version |
| `POST /dashboards/{id}/pins` | `{widget_id, slot, expected_revision}` | 201, `DashboardView`; adds a version |
| `GET /dashboards/{id}/versions` | | 200, `DashboardVersion[]`, oldest first |
| `GET /dashboard-versions/{version_id}` | | 200, `DashboardVersion` |
| `POST /dashboards/{id}/runs` | optional `{time_range?}` | 201, `Run` |

`DashboardView` is `{dashboard: Dashboard, version: DashboardVersion | null}`: what the
dashboard points at, so a client gets the slots and the revision for its next write in one
answer. Every mutation answers with the new view.

`Slot` is `{name, description?, widget_id?, layout?}` as in `core/models/dashboards.py`.

### Viewing a dashboard at one run

A dashboard shows one run at a time: `POST /dashboards/{id}/runs` starts a run for
`time_range` (default: the dashboard's `default_time_range`) through `RunService.start`,
acting as `Actor(user, "web")`, and returns it. Every widget on the dashboard then reads
that run, `GET /widgets/{id}/data?run_id=<run>`, so the dashboard is one consistent cut. A
run is project-wide, not tied to a dashboard version: a new version needs no new run.
Until workstream J adds time-range pushdown, the range is recorded on the run but sources
return everything.

## MCP tools

A write names the revision it read (`expected_revision`); a mismatch comes back as a tool
error naming both revisions. The acting `Actor` is the calling agent. Tools that return a
dashboard return a `DashboardState`: `{dashboard, version, url}`, where `url` is
`/projects/{project_id}/dashboards/{id}`.

| Tool | Arguments | Does |
| --- | --- | --- |
| `create_dashboard` | `project_id, name` | A new empty dashboard; `DashboardState` |
| `list_dashboards` | `project_id` | `Dashboard[]` |
| `get_dashboard` | `dashboard_id` | `DashboardState`; read it before writing |
| `list_dashboard_versions` | `dashboard_id` | `DashboardVersion[]`, oldest first |
| `pin_widget` | `dashboard_id, widget_id, slot, expected_revision` | Adds a version; `DashboardState` |
| `edit_dashboard` | `dashboard_id, slots, expected_revision` | Replaces all slots; adds a version; `DashboardState` |
| `set_dashboard_time_range` | `dashboard_id, expected_revision, start?, end?` | ISO dates, both inclusive; `Dashboard` |
| `show_dashboard_in_session` | `session_id, expected_revision, dashboard_id?` | `SessionService.show_dashboard`; the revision is the session's; no `dashboard_id` clears the panel; `{session, url}` |

The tool names `pin_widget`, `edit_dashboard`, `set_dashboard_time_range` and
`show_dashboard_in_session` do not start with one of the verbs
`tests/test_api_mcp.py::test_tool_names_are_snake_case_verbs` lists; that test needs
`pin`, `edit`, `set` and `show` added.

## Frontend

| Path | Shows |
| --- | --- |
| `/projects/{id}/dashboards/{dashboard_id}` | The dashboard: its slots on the 12-column grid, all widgets on one run; the time range control; the version history; a button that starts a session from it. `?version=<number>` looks at an older version |

- **Time range.** By whole years (from 1 January, to 31 December); a blank end is open.
  "Show" starts a new run for the range (`POST /dashboards/{id}/runs`) and the frames
  reload on it; "Save as default" writes `default_time_range` with `PATCH`.
- **Runs follow the data.** The page keeps one run per range. When a source refresh
  changed data (the page's widget epoch increases), the run queries are invalidated and a
  new run is started, since the old run fixed the old snapshots.
- **Version history.** Newest first; "View" opens `?version=n`; "Restore" adds a new
  version with that version's slots.
- **Start a session from it.** Creates a session with `origin_dashboard_id` and sets the
  dashboard as its panel dashboard, then opens it.
- **Session panel.** `DashboardPanel` (`components/dashboards/dashboard-panel.tsx`) shows
  the panel dashboard beside the conversation in one column, in reading order, at the
  dashboard's default range, and refetches on `dashboard.changed`.
- **Pin to dashboard.** `PinActions` (`components/dashboards/pin-to-dashboard.tsx`) gives
  every widget card inside it a strip with "Pin to dashboard": choose a dashboard (or a new
  one) and a slot name (default: the widget's title). The pin is made on the dashboard's
  latest revision, read at that moment. The session page wraps the session record in it.
  Mechanism: `WidgetCard` has an optional `actions` prop and reads `WidgetCardActions`
  (`components/widget-card-actions.ts`), a context, so a page can add actions to cards that
  `SessionRecord` renders.
- **Project page.** A "Dashboards" section lists them and creates one.
- **Writes** go through `useDashboardWrite` (`components/dashboards/use-dashboard.ts`): it
  sends the revision the page last showed, so an edit by someone else in between is a 409;
  the dashboard is read again and a notice says so.
- **Not done here.** `AlertBadges({ dashboardId })` from workstream I is placed by
  integration; the dashboard page has no slot for it yet. Slot positions are not edited by
  drag: layout changes come from agents over MCP, or by restoring a version.

Query keys: `dashboardKeys` in `lib/api/dashboards.ts`: `list(projectId)` is
`['projects', id, 'dashboards']`, `view(id)` is `['dashboards', id]` (the dashboard events
invalidate it), `versions(id)` is under it, and runs are `['dashboard-runs', id, start, end]`.
