# Research agent, web tools and watched pages: design

2026-11-14 · Junction cut, frozen by Sun 2026-11-15 08:00 (Helsinki)

## Why

ada analyses the data it is given. For Equal Care Across Finland the open data is thin: deaths
and screening are published by county, but survival is by hospital district, waiting times are
not published openly, and the Cancer Registry's county report sits behind a bot wall. Today an
agent in ada cannot search the web, read a page or find a dataset, so these gaps stay gaps.

This adds three things:

1. **Web tools for every ada agent**: Exa search and Context.dev page reading and extraction.
2. **A research agent** on Gemini that you, or ada's session agent, hand a brief. It runs in its
   own session in the background, finds and adds real datasets with their provenance and
   licence, says plainly what does not exist, and reports back. You can open its session and
   chat with it.
3. **Watched pages**: Context.dev reads a page into a source, and a Context.dev monitor on that
   page refreshes the source when the page changes. That triggers ada's existing alert checks.
   This is the core of "Tell me when" (the team's Context.dev entry) inside ada.

It serves three entries at once: AstraZeneca (data quality and transparency is 20 % of the
score, actionability 30 %), the Context.dev tech challenge (Context.dev visibly in the core
flow), and the Gemini API tech challenge (the research agent is built on Gemini).

## Goals

- The health demo has more data than the seed: the research agent finds and adds at least one
  dataset that the seed does not have, and adds the Cancer Registry's county figures through
  Context.dev.
- Every dataset an agent adds records where it came from (address, publisher, licence, the
  search that found it, fetch time). The source card shows that.
- Delegation works both ways: a person starts research from the chat, and the session agent
  can delegate with a tool. The parent session shows the research as running, then its report.
- A page watched through Context.dev refreshes its source within a minute of the monitor's
  webhook, and an alert rule on it fires in-app.

## Non-goals

- The full merge of Tell me when into ada (ntfy push, the watch-list UI, its quick-add flow).
  That is phase two; Tell me when stays its own entry this weekend.
- Push notifications. Alerts stay in-app.
- Browser sources (Playwright), statistic operators, agent operators.
- Exa Websets (paid) and an Exa "research" endpoint. Search and contents only.
- Per-project API keys. Keys are platform-wide, as the model keys are today.

## Anti-goals

- **An agent that invents data.** A number that is model-extracted must say so in provenance,
  and the research report must name what it could not find instead of filling the gap.
- **Hidden spend.** No Exa or Context.dev call starts unless a person or an agent asked for it:
  either a tool call the session record shows, or a refresh of a source someone set up
  (a forced refresh, or a monitor's webhook). Context.dev reads are materialised as snapshots.
  Document sources therefore allow only `MANUAL` and `PUSH` freshness, never `TTL`, because
  the minute sweep would re-read an expired TTL source on its own
  (`core/services/sources/freshness.py:24`). Model calls are the existing per-turn spend and
  are not counted here. *(Builder's call, from the builder check.)*
- **A demo that depends on the network at judging time.** Tests replay recordings; the demo
  project is seeded and its research run done before the freeze.

## Approaches considered

| Approach | Trade-off | Verdict |
| --- | --- | --- |
| **A. Research as child sessions** | A second agent profile and a parent link on sessions. Reuses sessions, turns, the chat and the event stream, so delegation and chatting with it come almost free. Long searches do not block the person's chat. | **Picked** (Felix, 2026-11-14) |
| B. Same agent, more tools | Cheapest: only the web tools. No delegation, long searches block the chat, and the Gemini story is weaker. | Rejected |
| C. Gemini Deep Research as the agent | The strongest "why Gemini" line, but a black box that runs for minutes, cannot call ada's tools (so cannot add a dataset) and has no published price. | Optional tool inside A, stretch |

## Design

### 1. Web tools (ports, adapters, MCP tools)

Two outbound ports in `core/ports/`, each with an httpx adapter in `adapters/`, a dishka
provider in `composition/providers/` owning the client, and a fake in `tests/fakes.py`, the
way `HttpReader` is built.

- `WebSearch` (Exa): `search(query, scope, limit) -> list[SearchHit]` and
  `contents(urls) -> list[PageText]`. `scope` is `data | news | research | any`; `data` limits
  `includeDomains` to a fixed list of data portals (THL/Sotkanet, Statistics Finland, Finnish
  Cancer Registry, NORDCAN/IARC, Eurostat, OECD, WHO, Kela, Duodecim, data.gov sites,
  Zenodo, Kaggle, figshare), `research` to scholarly sites. A `SearchHit` carries url,
  title, published date and a snippet. Exa's `auto` search type.
- `PageReader` (Context.dev): `read(url) -> PageText` (Markdown via scrape, PDFs parsed),
  `extract(url, instruction, columns) -> list[dict]` (schema-shaped extraction), and
  `watch(url, webhook_url) -> Monitor{id, secret}` / `unwatch(id)` for monitors.
  Context.dev generates the webhook secret and returns it (verified in Tell me when, c8eeb08).

MCP tools (so every agent and any MCP client gets them), each recorded in the session like
other tool calls: `search_web(query, scope, limit)`, `read_page(url)`,
`extract_table(url, instruction, columns)`.

Keys come from the environment only: `EXA_API_KEY`, `CONTEXT_API_KEY`. With a key missing the
tool fails with a clear message ("web search is not configured: EXA_API_KEY is not set"),
and `system_status` lists which web tools are configured. Gemini keys stay where model keys
already are: a provider on the Settings page.

### 2. Document sources through Context.dev

`AccessKind.DOCUMENT` gets its reader. A document source's `options` say what to take from
the page: `{"extract": {"instruction": ..., "columns": [...]}}` turns it into rows through
`extract`; without `extract` the source is the page's Markdown as one row
(url, title, text). The reader returns `FetchedData` as JSON, so storage, snapshots and
pipelines are unchanged. Its probe returns nothing (no cheap change check); freshness is
`MANUAL` or `PUSH` (see Anti-goals); registering one with `TTL` fails with a message saying so.

### 3. Provenance and licence

`DataSource` gets an optional `provenance`:
`{publisher, licence, landing_page, found_by: {query, scope} | null, extracted_by_model: bool, note}`.
`register_source` and the HTTP route accept it; the research agent must fill it. A licence
it cannot establish is recorded as `licence: "unknown"` with the reason in `note`; the
source is still registered, the card shows "licence unknown", and the research report lists
it as such. Evidence is the publisher's own terms page or dataset metadata, linked in `note`.
*(Builder's call, from the builder check.)* Snapshots
persist `FetchedData.origin` (the final URL after redirects), which is dropped today.
One migration covers both. The source card in the frontend shows publisher, licence and a
link, and a "model-extracted" badge when `extracted_by_model` is set.

### 4. Watched pages (PUSH freshness)

- MCP tool `watch_source(source_id)` (and an HTTP route for the frontend) creates a
  Context.dev monitor on the source's address with webhook
  `{ADA_PUBLIC_URL}/api/hooks/context/{source_id}`, stores the monitor id and its secret
  (encrypted with the existing `SecretBox`) and sets the source's freshness to `PUSH`.
  `unwatch_source` deletes the monitor. `ADA_PUBLIC_URL` is a new env setting; without it
  watching fails with a clear message.
- The webhook route verifies the `x-context-signature` HMAC against that source's secret
  (same scheme as Tell me when's `src/app/api/hooks/context/route.ts`), answers 401 on a
  mismatch and 404 for an unknown source, and otherwise queues `refresh_source(force=True)`
  and answers 202. Repeated deliveries are harmless: a refresh with unchanged content writes
  no new snapshot.
- Nothing new is needed for alerts: `due()` already picks a rule whose source has a snapshot
  newer than its last check, and the minute cron checks it.
- A convenience tool `watch_page(url, instruction, columns, condition, title)` does the whole
  Tell me when flow in one call: document source, `watch_source`, a pass-through transform,
  a table widget and an alert rule. Stretch: the agent can do the same with the other tools.

### 5. The research agent (child sessions)

- **Profile.** A second agent setting next to the session agent: `research_agent`, a model id
  chosen on the Settings page (Gemini expected, for example `gemini/gemini-3.8-flash`). Unset,
  it falls back to the session agent's model. Its instructions (a second briefing in
  `core/services/agents/briefing.py`) say: answer the brief with data, prefer official
  statistics, add each usable dataset as a source with provenance, check a source loads
  before reporting it, and list what does not exist openly with where it looked.
- **Tools.** The toolbox gets a per-profile filter. The research agent gets: `search_web`,
  `read_page`, `extract_table`, the source tools (`register_source`, `refresh_source`,
  `list_sources`, `update_source`), `preview_operator`/`add_source_operator` to check a
  source loads, `watch_source`, and `report_back`. It does not get dashboard, report or
  alert tools. With a Gemini model it also gets Gemini's built-in Google Search and URL
  context, if pydantic-ai can combine them with function tools for that model; if not, it
  goes without them (Exa covers search).
- **Sessions.** `Session` gets `parent_session_id` and `agent` (`session | research`).
  `delegate_research(brief, title)` (MCP tool for the session agent, and an HTTP route behind a
  "Research" action in the chat) creates the child session in the same project, posts the
  brief as its first message (actor: the delegating agent or person), and queues its turn
  with the research profile. It returns at once with the child session id; the parent
  session gets a `delegation` entry that links to the child and shows its state
  (running, done, failed).
- **Report back.** `report_back(summary, source_ids, missing)` ends the research: it posts the
  report into the parent session as a message from the research agent, with the sources it
  added and what it could not find, and marks the delegation done. If the turn ends without
  calling it, the turn's final text is posted instead, marked incomplete. A failed turn marks
  the delegation failed with its error.
- **Chat.** The child session is a normal session: the person opens it from the parent's
  delegation entry or the session list (shown under its parent) and writes to it; those turns
  use the research profile. A follow-up turn may call `report_back` again; each report is a
  new entry in the parent.
- **Limits.** The research turn runs with a higher step limit than a chat turn (the
  `max_steps` already in the runtime), and each research session caps its paid web calls
  (Exa and Context.dev tool calls in that session) at a number set in settings, default 40.
  Over the cap the tools fail with a message telling the agent to report back. Refreshes of
  sources it added, later, are not counted against it.

### 6. Health demo payoff (what the research agent should find)

The seed already covers screening (Sotkanet 3621), deaths by county (StatFin 13u5), Nordic
lung survival (NORDCAN) and county shapes. The demo brief is Goal 3 of the national cancer
strategy (survival of poor-prognosis cancers to the Nordic level, mortality down 10 %,
treatment within target times, equal across regions):

- adds Sotkanet survival indicators 3625–3627 (hospital-district level) with THL's licence;
- adds the Cancer Registry's county-level figures read through Context.dev (the site blocks
  plain HTTP fetches), marked model-extracted where they come from a table extraction. This
  is unproven: the registry's statistics are an interactive application whose CSV export
  needs a browser session. The first implementation task is a feasibility check with the real
  key on the registry's published county pages or PDFs. If Context.dev cannot read a usable
  table, this item drops and the report names the registry under what it could not get, with
  the reason; the demo still has the Sotkanet survival data. *(Builder's call.)*
- reports that open waiting-time-to-treatment data by county does not exist, with the places
  it looked, which is the actionable finding for AstraZeneca.

Before the freeze, the demo project gets this run done and saved, so judging does not wait
on the web.

## Constraints

- ada is Benjamin's repository: keep its hexagonal layout (`core` → `ports` → `adapters` →
  `composition`), `tach check --exact` passing, its naming and its lean comments. He agreed
  to this work in principle; the branch goes to him as one PR.
- Tests replay recorded HTTP answers (`Replay`); no test calls Exa, Context.dev or Gemini
  live. Recordings are made once with real keys and committed without the keys.
- One migration for all schema changes, in the repository's migration style.
- Deploy: the branch is built on the VM like `deploy-verda` until ada's GitHub Actions run
  (they currently fail at startup on `main`). Keys go into `/opt/ada/.env.local` by hand.
- Time: frozen by Sun 08:00. Order of value if time runs short: web tools → provenance →
  research agent → document source → watched pages → `watch_page` → Deep Research.

## Left to the builder

- Exact Exa and Context.dev request shapes, read from their current docs; field names of
  `SearchHit` and `PageText`.
- The domain lists per scope (start from the list above).
- How the frontend draws the delegation entry and the child session in the list, within the
  existing components; the "Research" chat action's placement.
- Whether `watch_page` lands, by time.
- The research briefing's wording, within the rules in section 5.
