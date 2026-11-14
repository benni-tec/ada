# Research agent, web tools and watched pages: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ada web search and page reading, Context.dev page sources with monitor-driven refresh, provenance on datasets, and a Gemini research agent that runs as a delegated child session.

**Architecture:** Two new outbound ports (`WebSearch` for Exa, `PageReader` for Context.dev) with httpx adapters, exposed as MCP tools so every agent gets them. `AccessKind.DOCUMENT` gets a reader on `PageReader`; a webhook route turns Context.dev monitor deliveries into forced refreshes, which the existing alert sweep picks up. The research agent is a second agent profile: a session with `agent = research` runs with its own model, briefing and tool filter, and reports into its parent session.

**Tech Stack:** Python 3.14, FastAPI, FastMCP, pydantic-ai, dishka, SQLAlchemy + Alembic, taskiq, DuckDB; React + openapi-fetch frontend; moon.

**Spec:** `docs/superpowers/specs/2026-11-14-research-agent-design.md` (read it first; it is the authority).

**Repo:** `~/projects/ada-wt/research` on the dev box (`ssh dev-codex`), branch `research-agent`. Paths below are relative to it; `B/` = `services/backend/src/ada/`, `T/` = `services/backend/tests/`, `F/` = `services/frontend/src/`.

## Global Constraints

- Keep ada's hexagonal layout: port Protocol in `B/core/ports/`, adapter in `B/adapters/<name>/`, dishka provider in `B/composition/providers/`, fake in `T/fakes.py`. `moon run backend:lint` (ruff + `tach check --exact`) and `backend:format` must pass; edit `services/backend/tach.toml` only if a new module needs a boundary entry.
- Run `moon run backend:test backend:lint backend:format` before every backend commit; `moon run frontend:lint frontend:typecheck frontend:test` before every frontend commit. Real-DB tests need `moon run root:infra` (PostgreSQL on 5434, Valkey).
- No test reaches the network or spends credits: HTTP goes through recorded answers (`T/recordings/`, the `Replay` pattern in `T/fakes.py`). Recordings never contain an API key, a webhook secret or a signature.
- Keys only from the environment: `EXA_API_KEY`, `CONTEXT_API_KEY` (both `SecretStr | None`, unprefixed, in `B/config.py` `Settings`), plus `ADA_PUBLIC_URL` (`str | None`). Never print or log a key. Values for live checks are in `~/ada-vm.env.local` on the dev box (mode 600): `set -a; . ~/ada-vm.env.local; set +a` in the shell that needs them; never `cat` it.
- A missing key makes the tool fail with exactly this shape of message: `"web search is not configured: EXA_API_KEY is not set"`, `"page reading is not configured: CONTEXT_API_KEY is not set"`, `"watching is not configured: ADA_PUBLIC_URL is not set"`.
- One Alembic migration for all schema changes: `B/adapters/db/migrations/versions/0006_research_and_web.py`, revision `"0006"`, down_revision `"0005"`, in the style of `0005_agent_configuration.py`.
- Research call cap default: `40` paid web tool calls (Exa + Context.dev tool calls) per research session.
- Document sources accept freshness `MANUAL` or `PUSH` only; `TTL`/`PROBE` fail with `Invalid("A document source refreshes only by hand or when its monitor fires (freshness manual or push)")`.
- Webhook signature: header `x-context-signature: t=<unix>,v1=<hex>`; HMAC-SHA256 over `f"{t}.{raw_body}"` with the source's monitor secret; reject when `|now - t|` exceeds the tolerance used in Tell me when's `~/projects/tell-me-when/src/providers/monitors.ts` (read it; same constant); constant-time compare.
- Commits: no AI attribution lines, no co-author trailers. Short imperative subjects in the repo's style ("Add …", "Let …").
- Lean tests and comments: a few meaningful behaviour tests per task, in the existing feature files (`T/test_sources.py`, `T/test_agent.py`, `T/test_api.py`, …), not new files unless a feature is new (`T/test_web.py` is allowed).
- Do not push. The controller tells Felix what to push.

## Review Focus

1. **Webhook abuse:** an unsigned, wrongly signed, stale-timestamp or unknown-source delivery must not queue a refresh (401/404), and the secret must never appear in a response, log or event.
2. **Spend leaks:** a document source must never be refreshed by the minute sweep; a research session over its cap must get the cap message, not more calls; a person's follow-up chat in a research session must still use the research model and filter.
3. **Report back twice / never:** a research turn that ends without `report_back` posts its final text once, marked incomplete; a failed research turn marks the delegation failed; a person-delegated report never queues a parent turn.
4. **Missing configuration:** with `EXA_API_KEY`, `CONTEXT_API_KEY`, `ADA_PUBLIC_URL` or the research model unset, every affected tool fails with the clear message and the rest of ada keeps working (startup must not fail).
5. **Existing data:** the migration runs on the deployed database with the seeded project (existing sessions become `agent = session`, `parent_session_id = NULL`; existing sources keep `provenance = NULL`), and the seed still runs.

---

### Task 0: Feasibility checks and recordings (no product code)

**Model:** standard. Live network, real keys; output is recordings and a short findings file.

**Files:**
- Create: `T/recordings/exa-search-data.json`, `T/recordings/exa-contents.json`, `T/recordings/context-scrape.json`, `T/recordings/context-extract.json`, `T/recordings/context-monitor-create.json` (secrets replaced by `"test-secret"`), index file `T/recordings/web.json` (same shape as `sources.json`: `{"exchanges": [{method, url, status, content_type, body, request?}]}`)
- Create: `docs/superpowers/specs/2026-11-14-research-feasibility.md`

- [ ] **Step 1:** Read Exa's and Context.dev's current API docs (search + contents; scrape/markdown, extract with a JSON schema, monitors create/delete and webhook payload). Note exact endpoints, auth headers and response fields in the findings file.
- [ ] **Step 2:** With the keys from `~/ada-vm.env.local`, record: one Exa search (`"cancer survival by hospital district Finland"`, `includeDomains` = the `data` scope list from the spec, 5 results), one Exa contents call for one hit, one Context.dev scrape of `https://sotkanet.fi/sotkanet/en/metadata/indicators/3625`, one extract of a table from a page, one monitor create on a harmless page (then delete it). Strip keys, secrets and signatures.
- [ ] **Step 3: Cancer Registry check.** Try Context.dev scrape and extract on the Finnish Cancer Registry's public county-level statistics pages or PDFs (start from `https://syoparekisteri.fi/` and its statistics/report pages). Record in the findings file: which URL, whether a usable county table came back, and the rows. If none, say so and why.
- [ ] **Step 4: Gemini built-ins.** Only if a Gemini key is available (ask the controller; Felix adds it): check whether pydantic-ai (the version in `uv.lock`) can run a `GoogleModel` with built-in Google Search / URL context **and** function tools in one agent on `gemini-3.8-flash`. Write the answer and the exact pydantic-ai names (`builtin_tools=[...]`) in the findings file. No key: write "unchecked".
- [ ] **Step 5: Commit** recordings and findings: `git commit -m "Record Exa and Context.dev answers for the web tools"`.

### Task 1: Web ports, adapters and settings

**Model:** standard.

**Files:**
- Create: `B/core/models/web.py`, `B/core/ports/web.py`, `B/adapters/web/__init__.py`, `B/adapters/web/exa.py`, `B/adapters/web/context.py`, `B/composition/providers/web.py`
- Modify: `B/config.py` (three settings), `B/composition/__init__.py` (if providers are listed there), `T/fakes.py` (fakes + a `Replay` variant over `web.json`)
- Test: `T/test_web.py`

**Interfaces (produces):**
- `B/core/models/web.py`: `class SearchScope(StrEnum): DATA="data"; NEWS="news"; RESEARCH="research"; ANY="any"`; `class SearchHit(DomainModel): url: str; title: str; published: str | None = None; snippet: str = ""`; `class PageText(DomainModel): url: str; title: str | None = None; text: str`; `class Monitor(DomainModel): id: str; secret: SecretStr`; `class WebNotConfigured(Invalid)` (or reuse `Invalid` with the exact messages from Global Constraints).
- `B/core/ports/web.py`:
  - `class WebSearch(Protocol)`: `async def search(self, query: str, scope: SearchScope, limit: int) -> Sequence[SearchHit]`; `async def contents(self, urls: Sequence[str]) -> Sequence[PageText]`.
  - `class PageReader(Protocol)`: `async def read(self, url: str) -> PageText`; `async def extract(self, url: str, instruction: str, columns: Sequence[str]) -> list[JsonObject]`; `async def watch(self, url: str, webhook_url: str) -> Monitor`; `async def unwatch(self, monitor_id: str) -> None`.
- Adapters `ExaSearch(client, api_key)` and `ContextPages(client, api_key)`; with `api_key is None` every method raises the "not configured" `Invalid`. Domain lists per scope live in `B/adapters/web/exa.py` as module constants.
- Provider `WebProvider` (APP scope) owning one `httpx.AsyncClient` (reuse `create_client()` from `B/adapters/sources/http.py`), providing `WebSearch` and `PageReader` from `Settings`.
- Fakes: `FakeWebSearch`, `FakePageReader` (record calls, return canned results), `WebReplay` handler over `T/recordings/web.json`.

- [ ] **Step 1: Write failing tests** in `T/test_web.py`: `test_exa_search_sends_data_domains_and_parses_hits` (Replay; asserts the request's `includeDomains` equals the `DATA` list and hits have url/title), `test_context_read_and_extract` (Replay; text non-empty, extract returns list of dicts with the requested columns), `test_monitor_secret_comes_from_the_response` (Replay; `Monitor.secret.get_secret_value() == "test-secret"`, request body has no `secret` key), `test_missing_key_fails_clearly` (both adapters with `None` key raise with the exact messages).
- [ ] **Step 2:** Run `moon run backend:test -- -k web` → FAIL (modules missing).
- [ ] **Step 3:** Implement models, ports, adapters, settings fields, provider, fakes.
- [ ] **Step 4:** `moon run backend:test backend:lint backend:format` → PASS.
- [ ] **Step 5: Commit** `"Add Exa search and Context.dev page reading behind ports"`.

### Task 2: Schema for provenance, monitors, child sessions and the research model

**Model:** standard.

**Files:**
- Create: `B/adapters/db/migrations/versions/0006_research_and_web.py`
- Modify: `B/core/models/sources.py`, `B/core/models/runs.py` (Snapshot), `B/core/models/sessions.py`, `B/core/models/agents.py` (`AgentSettings`, `AgentSettingsView`, `ModelList`), `B/adapters/db/tables.py`, the matching repositories in `B/adapters/db/*_repositories.py` and `B/adapters/memory/` twins, `B/core/services/sources/service.py` (`register` takes `provenance`), `B/entrypoints/mcp/tools/sources.py` + `B/entrypoints/http/routers/sources.py` (accept `provenance`), source fetch path that builds a Snapshot (persist `FetchedData.origin`).
- Test: `T/test_database.py`, `T/test_sources.py`

**Interfaces (produces):**
- `class FoundBy(DomainModel): query: str; scope: str`
- `class Provenance(DomainModel): publisher: str | None = None; licence: str | None = None; landing_page: str | None = None; found_by: FoundBy | None = None; extracted_by_model: bool = False; note: str | None = None`
- `DataSource.provenance: Provenance | None = None`; `DataSource.monitor_id: str | None = None` (written by watch, outside the revision like `last_checked_at`). The monitor secret is stored only as `data_sources.monitor_secret_encrypted` (Text, via `SecretBox`), never on the model; repository methods `set_monitor(source_id, monitor_id: str | None, secret_encrypted: str | None)` and `monitor_secret_encrypted(source_id) -> str | None`.
- `Snapshot.origin: str | None = None`.
- `class SessionAgent(StrEnum): SESSION="session"; RESEARCH="research"`; `Session.agent: SessionAgent = SessionAgent.SESSION`; `Session.parent_session_id: Id | None = None`.
- `EntryKind.DELEGATION = "delegation"` (`ref` = child session id) and `EntryKind.REPORT = "report"` (`ref` = child session id; `text` = the report).
- `AgentSettings.research_agent: str | None = None`; `ModelList.research_agent`, `AgentSettingsView.research_agent` likewise; `"research_agent"` as a purpose in `ModelInfo.purposes`. Deleting its model clears it, as for `session_agent`.
- Migration: columns `data_sources.provenance` (JSON, null), `data_sources.monitor_id` (Text, null), `data_sources.monitor_secret_encrypted` (Text, null), `snapshots.origin` (Text, null), `sessions.agent` (String(16), not null, server_default `'session'`), `sessions.parent_session_id` (Uuid, FK sessions.id ON DELETE SET NULL, index), `agent_settings.research_agent` (Text, null). Entry kinds are strings, so no enum migration unless the column is an enum (check).

- [ ] **Step 1: Failing tests:** `test_migration_0006_keeps_existing_rows` (upgrade from 0005 with a session and source row → defaults as in Review Focus 5); `test_register_source_keeps_provenance` (round trip, including `found_by`); `test_snapshot_keeps_origin` (fake reader with `origin="https://final/url"` → stored snapshot has it).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement migration, models, tables, repositories (DB and memory), service and tool/route parameters. `register_source`'s docstring tells agents to fill `provenance` with publisher, licence (`"unknown"` with the reason in `note` when it cannot be established) and `found_by`.
- [ ] **Step 4:** Full backend checks → PASS. Also run `uv run ada migrate` against the dev database once.
- [ ] **Step 5: Commit** `"Keep provenance, monitors and child sessions in the schema"`.

### Task 3: Web tools for every agent

**Model:** cheap-to-standard (pattern copy).

**Files:**
- Create: `B/entrypoints/mcp/tools/web.py`
- Modify: `B/core/models/health.py` + system status service (configured flags), `T/test_api.py` or `T/test_web.py`

**Interfaces (produces):** MCP tools
- `search_web(query: str, scope: SearchScope = SearchScope.DATA, limit: int = 8, session_id: Id | None = None) -> Sequence[SearchHit]`
- `read_page(url: str, session_id: Id | None = None) -> PageText` (text truncated to 20 000 characters, with a note when truncated)
- `extract_table(url: str, instruction: str, columns: list[str], session_id: Id | None = None) -> list[JsonObject]`
- Each takes `session_id` so the in-platform toolbox fills it and Task 6 can count calls per session. Docstrings are the LLM-facing descriptions: say what each costs ("one paid call"), and that rows from `extract_table` are model-extracted.
- `Health` gains `web_search: bool`, `page_reading: bool`, `watching: bool` (configured or not).

- [ ] **Step 1: Failing tests:** `test_web_tools_are_listed_for_the_agent` (InProcessToolbox lists the three); `test_search_web_tool_uses_the_port` (container with `FakeWebSearch`, MCP call returns its hits); `test_system_status_reports_web_configuration`.
- [ ] **Step 2–4:** Run → FAIL; implement; full checks → PASS.
- [ ] **Step 5: Commit** `"Give agents web search, page reading and table extraction"`.

### Task 4: Document sources through Context.dev

**Model:** standard.

**Files:**
- Create: `B/adapters/sources/document.py` (`DocumentReader(pages: PageReader, clock: Clock)` implementing `SourceReader`)
- Modify: `B/adapters/sources/http.py` (`HttpSourceReaders` installs the document reader), `B/composition/providers/sources.py` (pass `PageReader`), `B/core/services/sources/service.py` (freshness rule from Global Constraints on register and update), `register_source` docstring (access_kind `"document"`, `options.extract`)
- Test: `T/test_sources.py`

**Interfaces:** `options = {"extract": {"instruction": str, "columns": [str, ...]}}` → `fetch` returns `FetchedData(content=json rows, format=JSON, origin=url)`; without `extract` → one row `{"url", "title", "text"}`. `probe` returns `None`. `format` must be `json` for document sources (fail otherwise with a clear `Invalid`).

- [ ] **Step 1: Failing tests:** `test_document_source_extracts_rows` (FakePageReader; refresh → snapshot with the rows); `test_document_source_without_extract_is_one_page_row`; `test_document_source_rejects_ttl` (exact message); `test_refresh_sweep_skips_document_sources` (a PUSH document source is never due in `refresh_due_sources`).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"Read document sources through Context.dev"`.

### Task 5: Watched sources and the monitor webhook

**Model:** standard (security-relevant; reviewed by Codex with Review Focus 1).

**Files:**
- Create: `B/entrypoints/http/routers/hooks.py`, `B/core/services/sources/watching.py` (or methods on `DataSources`), `B/entrypoints/mcp/tools/watching.py`
- Modify: `B/core/services/ports/sources.py`, `B/entrypoints/http/routers/sources.py` (`POST /sources/{id}/watch`, `DELETE /sources/{id}/watch`), HTTP app router registration if not auto-discovered
- Test: `T/test_sources.py`, `T/test_api.py`

**Interfaces (produces):**
- `SourceService.watch(id: Id) -> DataSource` — needs `ADA_PUBLIC_URL`; calls `PageReader.watch(source.address, f"{public_url}/api/hooks/context/{id}")`, encrypts the secret with `SecretBox`, stores id + secret, sets freshness `PUSH`. Watching an already-watched source replaces its monitor (unwatch the old one first).
- `SourceService.unwatch(id: Id) -> DataSource` — deletes the monitor (ignore a 404 from Context.dev), clears both fields, freshness back to `MANUAL`.
- `SourceService.verify_push(id: Id, raw_body: bytes, signature: str | None, now: datetime) -> bool`.
- Route `POST /api/hooks/context/{source_id}`: unknown source or no monitor → 404; bad signature → 401; else queue `refresh_source(force=True)` after commit via `TaskDispatcher` and answer 202 `{"status": "queued"}`. Mounted under the same `/api` prefix as the other routers (check how the gateway forwards `/api`).
- MCP tools `watch_source(source_id: Id) -> DataSource` and `unwatch_source(source_id: Id) -> DataSource`.

- [ ] **Step 1: Failing tests:** `test_watch_stores_encrypted_secret_and_sets_push` (FakePageReader; DB column is not the plain secret; model has no secret); `test_watch_without_public_url_fails_clearly`; `test_hook_rejects_bad_signature` (401, nothing queued); `test_hook_rejects_stale_timestamp`; `test_hook_unknown_source_is_404`; `test_hook_good_signature_queues_forced_refresh` (202, memory dispatcher got `refresh_source(id, force=True)`); `test_pushed_snapshot_makes_alert_rule_due` (end to end with fakes: new snapshot → `due()` true).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"Refresh watched sources when their Context.dev monitor fires"`.

### Task 6: The research agent

**Model:** most capable (cross-cutting judgement in the agent service).

**Files:**
- Create: `B/entrypoints/mcp/tools/research.py`, `B/core/services/agents/research.py` (delegation and report-back logic)
- Modify: `B/core/services/agents/service.py`, `B/core/services/agents/briefing.py` (research briefing), `B/core/services/agents/settings.py` (`set_research_agent`, catalog purpose, fallback), `B/entrypoints/http/routers/settings.py` (set research agent), `B/entrypoints/http/routers/sessions.py` (`POST /sessions/{id}/research` → delegate as the person), `B/core/ports/agents.py` + `B/entrypoints/mcp/agent.py` (tool filter by profile), `B/entrypoints/mcp/tools/web.py` (call cap), `B/adapters/llm/runtime.py` (Gemini built-ins only if Task 0 found them usable)
- Test: `T/test_agent.py`, `T/test_api.py`

**Interfaces (produces):**
- `AgentToolbox.connect(agent: Actor, session_id: Id, profile: SessionAgent = SessionAgent.SESSION)`; `InProcessToolbox` keeps, for `RESEARCH`, only `RESEARCH_TOOLS = {"search_web", "read_page", "extract_table", "register_source", "refresh_source", "list_sources", "update_source", "add_source_operator", "preview_operator", "watch_source", "report_back"}`; for `SESSION`, everything except `LEFT_OUT` and `report_back`.
- `LanguageModels.research_agent()` resolution: `research_agent` setting, else `session_agent`, else none (then delegation fails with `Invalid("No research agent model is configured")`).
- `AgentTurns.post_message`: when `model is None`, chooses `research_agent` for a session whose `agent is RESEARCH`, else `session_agent` (Review Focus 2).
- `AgentTurns.run`: uses the research briefing and `profile=RESEARCH` for research sessions; `MAX_RESEARCH_STEPS` (e.g. 60) instead of `MAX_STEPS`. After a research turn finishes: if it called `report_back` in this turn, nothing more; if it finished DONE without it, post its final text as a report marked `"(incomplete: ended without a report)"`; if FAILED, post a report `"Research failed: <error>"`.
- `Research.delegate(parent_session_id: Id, brief: str, title: str, actor: Actor) -> Session` — creates the child (`agent=RESEARCH`, same project), adds a `DELEGATION` entry in the parent (`ref` = child id, `text` = title), posts `brief` into the child via `post_message(child.id, brief, actor, model=<research model>)`. Returns at once.
- `Research.report(child_session_id: Id, summary: str, source_ids: list[Id], missing: list[str]) -> SessionEntry` — composes the report text (summary, added sources by name, "Not found:" list), adds a `REPORT` entry in the parent with actor = the research agent. If the delegation's actor was an agent (the `DELEGATION` entry's actor kind), also queue a parent turn the way `post_message` does (same model selection, `session_agent`); if a person delegated, no turn.
- MCP tools: `delegate_research(brief: str, title: str, session_id: Id) -> Session` (session agent only) and `report_back(summary: str, source_ids: list[Id], missing: list[str], session_id: Id) -> SessionEntry` (research only).
- Call cap: web tools count calls per research session (count `ToolPart`s of web tools in that session's turns, or a counter column if simpler) and fail with `"This research session has used its 40 web calls; call report_back with what you have"` past the cap.
- Research briefing rules (spec §5): answer with data; prefer official statistics; add each usable dataset with `register_source` and full provenance; `refresh_source` and `preview_operator` to check it loads before reporting; never invent numbers; list what does not exist openly and where it looked; finish with `report_back`.
- Check and document (findings file or test) whether two turns of the same session can run at once in the taskiq worker; if they can, a parent turn queued by a report while another parent turn runs must wait (Review Focus 3).

- [ ] **Step 1: Failing tests** (FunctionModel scripts the model): `test_delegate_creates_child_and_queues_research_turn`; `test_research_turn_gets_only_research_tools`; `test_person_follow_up_in_research_session_uses_research_model`; `test_report_back_posts_into_parent_without_turn_when_person_delegated`; `test_report_back_queues_parent_turn_when_agent_delegated`; `test_research_turn_without_report_posts_incomplete_report_once`; `test_failed_research_turn_reports_failure`; `test_web_call_cap`.
- [ ] **Step 2–4:** FAIL → implement → full checks PASS.
- [ ] **Step 5: Commit** `"Add a research agent that works in delegated sessions"`.

### Task 7: Frontend

**Model:** standard.

**Files:**
- Modify: `services/frontend/openapi.json`, `F/lib/api/schema.d.ts` (regenerate with `moon run frontend:<openapi task>` from `services/frontend/moon.yml:48`), `F/components/settings/agents.tsx` (research agent picker beside the session agent), `F/components/provenance.tsx` + `F/components/settings/data-sources.tsx` (publisher, licence or "licence unknown", landing link, "model-extracted" badge; Watch / Stop watching action and a "watched" marker), `F/components/project-sidebar.tsx` (research sessions under their parent, with a small "research" label), `F/components/session-record.tsx` (render `delegation` entries as a card linking to the child session with its state from the child's latest turn: running / done / failed; render `report` entries as a message from the research agent with a link to the child), `F/components/chat/composer.tsx` (a "Research" action that sends the draft as a brief to `POST /sessions/{id}/research`)
- Test: the existing component tests next to the files touched (one or two per feature)

- [ ] **Step 1:** Regenerate the API client; `frontend:typecheck` shows what broke.
- [ ] **Step 2: Failing tests:** session record renders a delegation card with a link and state; provenance shows "licence unknown"; sidebar nests a research session under its parent.
- [ ] **Step 3–4:** Implement in the existing components and styles (no new UI library); frontend checks PASS. Check the screens once in the browser against `moon run :dev` (mock agent is fine).
- [ ] **Step 5: Commit** `"Show research sessions, delegations, provenance and watching"`.

### Task 8: Deploy and the demo run

**Model:** controller (needs Felix for the Gemini key; no subagent).

- [ ] **Step 1:** Rebuild on the VM with the ship script (`/tmp/ada-ship.sh` on the dev box, pointing at branch `research-agent`); migration 0006 runs; health OK.
- [ ] **Step 2:** Felix adds the Gemini provider and models on the Settings page and sets the research agent.
- [ ] **Step 3:** In the "Nordic cancer care" project, delegate the Goal 3 brief (spec §6) and check the report: Sotkanet survival sources added with provenance, Cancer Registry per Task 0's finding, "not found" list includes open waiting-time data by county.
- [ ] **Step 4:** Watch one page with a document source and an alert rule; trigger a change or a test delivery; the alert fires in-app.
- [ ] **Step 5:** Note what ran and what didn't in the vault project file.

### Task 9 (stretch, only if time before 06:00 Sun): `watch_page` and `deep_context`

- `watch_page(url, instruction, columns, condition, title, session_id)` composes Task 4 + Task 5 + `add_source_operator` + `add_transform` + `create_widget` + `create_alert_rule`.
- `deep_context(question)`: Gemini Deep Research via google-genai Interactions (`agent="deep-research-preview-04-2026"`, `background=True`), polled by a worker task, result posted as a report. Only with Felix's go.

## Final review

Codex on the dev box (read-only `codex exec`, the hostile-review skill) over `deploy-verda..research-agent`, with Review Focus as the lens; one fix wave; then Felix pushes `research-agent` and opens one PR to Benjamin.
