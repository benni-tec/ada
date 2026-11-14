# Contract: wave 5, the web through ADA, and every tool call in a session

Decided with the user:

- ADA proxies a few of Context.dev's tools on **ADA's own key**, so no customer needs a
  Context.dev account; external clients profit as much as the in-platform agent.
- **Every ADA tool call requires a `session_id`**, and the session shows each call, also
  when an external agent makes it.
- Context.dev also becomes a way to read **web pages as data sources**.

Three agents work at the same time, each in its own worktree.

| Agent | Builds | Owns |
| --- | --- | --- |
| Web | A, B | `adapters/web/` (new), `core/services/exploration/` (new), `entrypoints/mcp/tools/web.py` (new), the `web` access kind in `core/models/sources.py` and `adapters/sources/`, migration `0006` |
| Sessions | C, D | the MCP layer (`entrypoints/mcp/injection.py`, `server.py`, a middleware), every existing tool module's `session_id` parameter, session entries for tool calls (models, repositories, migration `0007`), the frontend's session record |
| Settings | E, F | agent instructions (the agent settings service and repositories, `core/services/agents/briefing.py`, the project's instructions, migration `0008`), the frontend's settings (`components/settings/`, the settings route, the sidebar's gear) |

The Web agent adds `session_id` (required) to its own new tools; the Sessions agent makes it
required everywhere else. Migrations: Web takes `0006`, Sessions `0007` (down revision
`0006`), Settings `0008` (down revision `0007`); integration renumbers if needed.

## A. Web exploration (Web)

MCP tools, each with required `project_id` and `session_id`:

| Tool | Context.dev | Forwarded | Returns |
| --- | --- | --- | --- |
| `web_search(query, num_results=10, include_domains?, exclude_domains?, country?, languages?)` | `web-search` | those, `numResults` ≤ 20 | `{results: [{title, url, snippet}], note}` |
| `web_read(url, max_chars=20000)` | `web-scrape`, Markdown only | `url`, `formats: ["markdown"]` | `{url, title?, markdown (cut to max_chars ≤ 60000), truncated, note}` |
| `web_map(domain, search?, max_links=50)` | `web-map` | those | `{links: [{url, title?}], note}` |

- Called through Context.dev's hosted MCP (`https://mcp.context.dev/mcp`, Streamable HTTP,
  `Authorization: Bearer <key>`) or its REST API, behind a port `WebExplorer`
  (`core/ports/web.py`); the key is `Settings.context_dev_api_key` (exists:
  `CONTEXT_DEV_API_KEY` or `CONTEXT_API_KEY`). No key: a readable refusal.
- Every call is tagged `["ada", "project:<id>"]` (Context.dev's `tags`).
- Nothing else is forwarded: no screenshots, browser actions, webhooks, policies, batches,
  monitors, logs or usage, people or company data (those act on ADA's account or are
  personal data).
- **Budget**: calls per project per day, `Settings.web_daily_call_limit` (default 200),
  counted in a table `web_usage (project_id, day, calls)` (migration `0006`), checked and
  counted in its own short transaction (a refused or failed tool call is still counted
  once the request was sent). Over the budget: `Invalid("The web budget of this project
  (200 calls a day) is used up for today")`.
- Every answer carries the exploration note: "For your own exploration only. Do not show
  or quote this to the person: to present web data, register its URL as a source
  (register_source, access_kind \"web\" or \"document\") and build on it, so it can be
  traced." Tool descriptions and the server instructions say the same.

## B. Web pages as sources (Web)

- `access_kind: "web"`, `format: "html"` (add `html` to `DataFormat` if absent): the address is
  a page URL, read through Context.dev's scrape as Markdown.
- `options.extract`: `"pages"` (default: one row `page 1, text <markdown>`) or `"tables"`
  (the Markdown tables as `page, table, row, cells`), the same columns as document sources
  (`DOCUMENT_COLUMNS`) and the same Markdown converters (`adapters/sources/context_dev.py`:
  `markdown_pages`, `markdown_tables`).
- Freshness by `ttl` (no probe); a refresh whose Markdown did not change makes no snapshot
  (content hash, as today).
- Readable failures as for documents (no key, no credits, unreachable page).
- `register_source`'s description mentions it; `docs/contracts.md` documents A and B.

## C. A session for every tool call (Sessions)

- Every ADA MCP tool takes a **required** `session_id`, except: `list_projects`,
  `create_project`, `create_session`, `system_status`, and the widget's own `get_widget_data`
  (MCP Apps visibility `app`). A tool with a `project_id` checks that the session is in that
  project (`Invalid` otherwise); others check that it exists.
- A FastMCP middleware records **each call** as a session entry of a new kind
  `tool_call`: `{tool, arguments (values shortened: strings over 200 characters cut, lists
  over 10 items cut, SQL kept whole up to 2,000 characters), status: "ok" | "error",
  error (message) | null, duration_ms}`, with the calling actor, in **its own short
  transaction**, so a failed tool call is recorded too (its own unit of work rolled back).
  It publishes `session.entry_added` after that commit.
- Calls by the in-platform agent are **not** recorded this way: its turn already shows each
  call in its Trace.
- The in-process toolbox keeps filling in the turn's session id.
- Existing tools that already record an entry with a note (add_transform, create_widget, …)
  keep doing so; the tool-call entry is in addition, and the frontend folds them together
  (D).

## D. Showing tool calls (Sessions)

- In the session record, consecutive `tool_call` entries of one actor are one compact,
  collapsible group ("Claude Code used 6 tools"), drawn like the agent's Trace: each call's
  tool name, status (failed in red, with the error), duration, and its arguments on
  opening. Exploration calls (`query_operator`, `web_*`) are marked "explored, not shown".
- A tool call whose effect already has its own entry (an operator, a widget) is not drawn
  twice: the group links to it or omits it; your call.

## E. Instructions for the session agent (Settings)

- **Global instructions**: free text in the agent settings (`agent_settings.instructions`),
  for every project; e.g. a pasted skill such as Context.dev's. **Project instructions**:
  free text per project (`projects.agent_instructions`), e.g. "This project is about the
  AstraZeneca Equal Care challenge; answer in English; cite the strategy's page".
- Both are appended to the system prompt the briefing builds (`briefing.py`), after ADA's
  own rules, under headings ("Instructions for every project", "Instructions for this
  project"), each cut at 20,000 characters. ADA's own rules come first and are not
  replaceable (the exploration and traceability rules must hold).
- REST: the global text in `GET /settings/agent` and `PUT /settings/agent-instructions
  {instructions, expected_revision}`; the project's in the project (`agent_instructions`)
  and `PATCH /projects/{id}` (revision-checked as today). Not exposed as MCP tools.

## F. Settings as a modal (Settings)

- The sidebar's gear opens Settings as a large modal over the current page (the shadcn
  Dialog the app uses), with a side navigation in two groups:
  - **Global** (says "Shared by all projects"): Models and providers (today's agent
    section), Agent instructions (a textarea, saved with the revision), Web (the daily
    budget per project from `Settings.web_daily_call_limit`, read-only, and whether a
    Context.dev key is configured; read from a small `GET /settings/web` the Web agent
    does not build: add it here, reading only `Settings`).
  - **This project** (with the project's name): Data sources (today's section, with an
    "Upload a PDF" action that posts to `POST /projects/{id}/files` and registers a
    document source on the returned address, engine selectable: local or Context.dev),
    Agent instructions (the project's textarea).
- The modal is addressable (`?settings=<section>` on any project page, so links such as
  the chat's "configure in Settings" and the sidebar's data source links open the right
  section); Escape and × close it and return to the page. The `/settings` route may
  remain as a redirect to the modal.
- Keep the existing settings tests passing in spirit (adapt them to the modal).

## Not in this wave

Context.dev monitors as push freshness for web sources; Settings page for the web budget
and usage; `web-answers`.
