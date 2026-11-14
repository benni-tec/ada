# Reports (wave 2, workstream H)

What workstream H defined, to be folded into `docs/contracts.md` at integration. The spec's
"Reports", "Versions" and "OpenUI" sections say why; this says how.

## Where it lives

| Path | What it is |
| --- | --- |
| `core/services/reports/content.py` | The component tree: its blocks, how a tree is checked, filled and walked |
| `core/services/reports/versions.py` | Version numbers and the level a change needs |
| `core/services/reports/sources.py` | The generated sources list |
| `core/services/reports/service.py` | `Reports`, the `ReportService` |
| `core/services/reports/templates.py` | `Templates`, the `TemplateService` |
| `composition/providers/reports.py` | Binds both, at `Scope.REQUEST` |
| `entrypoints/http/routers/reports.py` | REST |
| `entrypoints/mcp/tools/reports.py` | MCP tools |
| Frontend `src/lib/api/reports.ts`, `src/components/reports/**`, `src/routes/projects/$projectId/reports/**` | Types, requests, queries; the report page and the generate form |

## The content tree

A report version's `content`, and a report template's, is a plain JSON tree:
`{"blocks": [...]}`. Every write is checked (`content.parse`); a wrong tree is `Invalid`
(422, or a tool error) with every problem and its path, e.g. `blocks[2].rows: not a field
of this block`.

| Block | Fields | Notes |
| --- | --- | --- |
| `heading` | `text` (1–500 chars), `level` 1, 2 or 3 (default 2) | |
| `text` | `text` (1–20 000 chars) | Plain text; a blank line starts a paragraph. No markup |
| `callout` | `text`, `tone` `note` / `finding` / `warning` (default `note`), `title` (default `""`) | |
| `widget` | `widget_id` (in a report) or `slot` (in a template), `caption` (default `""`) | The only block that shows data, and only by widget id |
| `section` | `title` (default `""`), `blocks` | Nests at most 4 deep |

- **Only widgets carry data.** A block takes exactly its fields: anything else (`rows`,
  `value`, a `widget_id` on a heading) is `Invalid`. A widget must exist and be in the
  report's project. Numbers typed into text cannot be detected; the tool descriptions tell
  agents to show a widget instead.
- **Limits.** At most 500 blocks; at least one in a report.
- **Stored form.** Defaults are filled in and `null` fields left out, so two equal trees
  are stored equally (the version level compares them).
- **`sources` is generated.** A stored report version's content is
  `{"blocks": [...], "sources": [...]}`. A caller that sends `sources` gets `Invalid`.
- **Templates.** A report template's widget blocks name a `slot` (not a `widget_id`);
  every declared slot appears exactly once and no undeclared one does. Without `content`
  the slots in their order make the tree. A dashboard template has no tree (`content` is
  `{}`); its slots carry the layout.
- **Slot layout.** `{x, y, w, h}`, whole numbers ≥ 0, on a 12-column grid (`x + w ≤ 12`);
  checked when a template is created. Slot names are unique and non-blank.

### Filling a template

`create` (REST `POST /projects/{id}/reports`, MCP `create_report`) with a `template_id`
and as content `{"slots": {"<slot>": "<widget id>", ...}}` instantiates a report template:
its tree with each slot block replaced by a widget block (the caption is kept). A slot with
a default `widget_id` may be left out; every other slot must be filled. The version records
the `template_id`. `add_version` keeps the latest version's `template_id` and accepts the
same `{"slots": ...}` form again. The template must be a `report` template of the project.

## Versions

A report starts at `1.0.0`. `add_version` and `generate_from_dashboard` compare against the
latest version (`Report.latest_version_id`):

| Level | When |
| --- | --- |
| Major | The set of operator ids behind the widgets changed. An operator's id is its identity, which covers its whole pipeline |
| Minor | Same operators; another run or time range |
| Patch | Same operators, run and range; the stored blocks differ (text, captions, order, another widget on the same operator) |
| — | Nothing differs: `Invalid` ("Nothing changed against version …") |

A given `bump` may be higher than the change needs (a changed definition the platform
cannot see) and never lower (`Invalid`). Major resets minor and patch, minor resets patch.
Versions are listed lowest first, by number (`1.10.0` after `1.9.0`).

- **Owner.** Exactly one of `session_id` and `dashboard_id`, in the report's project. An
  owner has at most one report of a name (`Invalid` otherwise: add a version instead).
- **Run and time range.** A version pins one run, which must be in the project, and
  records the run's time range; a different `time_range` is `Invalid`. The entry points
  start a run (`RunService.start`, for `time_range`) when no `run_id` is given.
- **Freezing.** Before a version is stored, the run executes each distinct widget operator
  (`RunService.execute`), so the run fixes the snapshot of every source the widgets read.
  The version then shows the same numbers for as long as it exists. An operator that
  cannot run fails the write (422 or 503).
- **Concurrency.** Adding a version moves `latest_version_id` with the report's revision,
  so two versions added at once conflict (409, both revisions). REST and MCP also take an
  optional `expected_revision`, checked before anything is written.
- **Event.** `report.version_created` with `{report_id, version_id, version}`, published
  through the transactional `EventPublisher` (after the commit; dropped on a rollback).

## Generating from a dashboard

`generate_from_dashboard(dashboard_id, name, actor, run_id?, time_range?)` reads the
dashboard and its current version through `DashboardService` (`get`, `current`):

- The tree is one widget block per filled slot, top to bottom then left to right on the
  grid (`layout.y`, then `layout.x`, missing as 0); empty slots are left out. No widgets is
  `Invalid`.
- Without `run_id` a run is started for `time_range`, or else the dashboard's
  `default_time_range`, by the acting actor. With `run_id`, a `time_range` must match it.
- When the dashboard already has a report of that name, this adds its next version with the
  inferred level; otherwise it creates the report, owned by the dashboard.
- The version records `dashboard_version_id`; `template_id` stays empty.

## The sources list

Generated when a version is made and stored in its content, never written by hand. Per
source operator behind the widgets (walking each widget operator's inputs; an `input`
operator that the run binds leads to what it is bound to, not to its default), ordered by
name:

| Field | Meaning |
| --- | --- |
| `data_source_id`, `name`, `access_kind`, `format` | The registered source |
| `address` | Where it was fetched from when the version was made (a later edit does not change it) |
| `operator_id` | The source operator; its lineage is the rest of the pipeline |
| `snapshot_id`, `fetched_at`, `content_hash` | The snapshot the version's run used; `null` only if the run fixed none |
| `widget_ids` | The version's widgets that rest on it, in reading order |

It is stored rather than worked out on reading because the inbound `ReportService` port
has no method for it and is frozen; a version is immutable, so the stored list cannot go
stale. See "Contract notes".

## REST

| Method and path | Does |
| --- | --- |
| `GET /projects/{id}/reports?session_id=&dashboard_id=` | The project's reports, oldest first, optionally only one owner's |
| `POST /projects/{id}/reports {name, content, run_id?, time_range?, session_id?, dashboard_id?, template_id?}` | Create; 201 with the `ReportVersion` 1.0.0 |
| `GET /reports/{id}` | The `Report` |
| `GET /reports/{id}/versions` | Its versions, lowest number first |
| `POST /reports/{id}/versions {content, run_id?, time_range?, bump?, expected_revision?}` | Add a version; 201 with the `ReportVersion` |
| `GET /report-versions/{version_id}` | One version |
| `GET /report-versions/{version_id}/sources` | Its sources list, typed (`ReportSource`) |
| `POST /dashboards/{id}/reports {name, run_id?, time_range?}` | Generate from the dashboard; 201 with the `ReportVersion` |
| `GET /projects/{id}/templates`, `POST /projects/{id}/templates {name, kind, slots, content?}` | List; create (201) |
| `GET /templates/{id}` | One template |

Errors follow `docs/contracts.md`: 404 for unknown ids in the path (and an unknown
`run_id`), 422 for an invalid tree, fill, owner, range or level (an unknown widget in the
content is 422, not 404), 409 with both revisions on a stale `expected_revision`.

## MCP tools

All act as the calling external agent. `create_report` and `add_report_version` carry the
content format in their descriptions.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `create_report` | `project_id, name, content`, optional `run_id, time_range, session_id, dashboard_id, template_id` | `ReportView` |
| `add_report_version` | `report_id, content`, optional `run_id, time_range, bump, expected_revision` | `ReportView` |
| `generate_report_from_dashboard` | `dashboard_id, name`, optional `run_id, time_range` | `ReportView` |
| `list_reports` | `project_id`, optional `session_id, dashboard_id` | `[{report, url}]` |
| `get_report` | `report_id`, optional `version` (a number like `"1.2.0"`; default the latest) | `ReportView` |
| `create_template` | `project_id, name, kind, slots`, optional `content` | `Template` |
| `list_templates` | `project_id` | `[Template]` |

`ReportView` is `{report, version, versions, url}`: the version with its tree and sources,
every version number lowest first, and the frontend address
`/projects/{project}/reports/{report}?version={number}`.

## Frontend

| Path | Shows |
| --- | --- |
| `/projects/{id}/reports/{report_id}` | A report; `?version=1.2.0` picks the version (default the latest). The tree with each widget in its frame at the version's run (`#widget=<id>&run=<run>`), the run, time range, dashboard version and template, the generated sources list, and per widget its pipeline (`GET /api/operators/{id}/lineage`, loaded when opened) and a link to the widget page at the run |
| `/projects/{id}/reports/new` | Generate a report from a dashboard: pick the dashboard (`?dashboard=<id>` preselects one), name it. Opens the new version |

- The project page has a "Reports" section (newest first, with the producing session or
  dashboard) and links to the generate form.
- Query keys (`reportKeys`): `['projects', id, 'reports']`, `['reports', id]`,
  `['reports', id, 'versions']`, `['report-versions', id, 'sources']`, `['templates', id]`,
  `['operators', id, 'lineage']`, `['projects', id, 'dashboards']`.
- `report.version_created` invalidates the project's reports and `['reports', report_id]`
  (which covers the versions).

## Contract notes for integration

- **`generate` is a new tool verb.** `tests/test_api_mcp.py::test_tool_names_are_snake_case_verbs`
  allows a fixed set of verbs and fails on `generate_report_from_dashboard`. Add
  `"generate"` to its set (this branch does not own that file, so that test fails here).
- **The sources list has no port method.** A cleaner contract would add
  `ReportService.sources(version_id) -> Sequence[ReportSource]` with a `ReportSource`
  model in `core/models/reports.py`. Until then the list is stored in the version's
  content and its shape is declared twice: `SourceEntry` (service, writing) and
  `ReportSource` (router, reading).
- **The dashboard list comes from workstream G.** The generate form reads
  `GET /api/projects/{id}/dashboards` (expected to answer `[{id, project_id, name, ...}]`)
  with a hand-written request, since the route is not in this branch's schema. After the
  merge, switch `listDashboards` in `src/lib/api/reports.ts` to the generated client, and
  link "Generate report" on G's dashboard page to `/projects/{id}/reports/new?dashboard=<id>`.
  The report page links a dashboard-owned report to `/projects/{id}/dashboards/{id}` with a
  plain anchor; make it a router `Link` once G's route exists.
- **`time_range` on create and add_version.** The port requires one; the entry points pass
  the run's when none is given. The service rejects any other range.
- **Sessions do not record reports.** `EntryKind` has no report kind, so a report written
  in a session appears in the session's report list (`?session_id=`), not in its record.
