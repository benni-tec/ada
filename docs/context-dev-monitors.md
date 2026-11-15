# Context.dev monitors

Public docs checked 2026-11-15; no authenticated API calls or test monitors.

- **Cost:** successful page/sitemap runs cost 1 credit, including unchanged checks and the initial baseline; page browser actions and search cost 2, extract costs 10. Failed/skipped runs cost 0. Creating/managing monitors costs 0, but creation queues a billable baseline. [Credits](https://docs.context.dev/account/credits), [creation](https://docs.context.dev/monitors/overview).
- **Schedules:** only `interval`; no documented cron, adaptive, auto or smart timing. Integer `frequency` 1–525,600; `unit` is `minutes`, `hours`, or `days`; total interval 10 minutes–365 days. Omission means daily. No plan-specific minimum is documented. Slots are staggered by monitor ID; schedule updates keep the baseline. [Schedules](https://docs.context.dev/monitors/schedules), [API schema](https://docs.context.dev/api-reference/monitors/create).
- **Monitor limits:** Free 10, Developer 100, Pro 1,000, Growth 5,000, Scale/Scale 2.5M 10,000. Paused monitors count. Legacy/custom entitlements differ; the stated 5,000-slot account was not independently checked. [Billing](https://docs.context.dev/account/billing#plan-limits), [limits](https://docs.context.dev/monitors/limits-and-errors).
- **Batch creation:** no documented bulk monitor-create endpoint; `POST /monitors` creates one. Batches scrape/crawl URLs, not create monitors. [API index](https://docs.context.dev/llms.txt), [create](https://docs.context.dev/api-reference/monitors/create), [batches](https://docs.context.dev/batches/submit).
- **Rate limits:** monitor management has a separate organization-wide 1,000 requests/minute bucket. Core reads have plan concurrency limits and legacy per-minute limits. [Rate limits](https://docs.context.dev/optimization/rate-limits).

For 30 plain page monitors, successful checks alone consume about 4,320 credits/day at 10min, 720 hourly, or 30 daily, plus baselines and ADA's reads after changes. 50,000 credits therefore last roughly 11.6, 69.4, or 1,667 days respectively before those additional costs. Monitor capacity is not a credit budget.

Decision: offer only `10min`, `hourly`, `daily`; omitted choices retain ADA's configured global interval. Existing monitors are untouched. Prefer daily for slow pages, hourly for news/daytime lists, and 10min only for explicitly urgent updates such as shortage lists.

## Bulk watching in ADA

- Research offers individual `register_source` and `watch_source`; its allowed tools exclude `build_pipeline`. Its prompt asks for `refresh_source(wait)`, `add_source_operator`, and `preview_operator` for each source too: at least 100–150 tool calls for 20–30 pages, before discovery/reporting. Session agents can batch registration through `build_pipeline`, but watching remains one call per page.
- Research allows 60 model requests, session agents 24 (not hard tool-call counts: models can issue several tool calls in a response). Turns have a 30-minute deadline. Research defaults to 40 paid web calls across its turns; reading and then refreshing 20 pages already uses 40 before search. Watch management itself does not use this cap or ADA's daily read budget; subsequent refreshes do.
- Each Context.dev request uses httpx with a 180-second timeout (10-second connect), without application retries/backoff. A 429/selected 5xx becomes a tool error. Each tool has its own transaction; earlier successful watches survive a later failure. Re-watching replaces the monitor and creates another baseline. Creation returns before baseline completion.
- Verdict: 20–30 existing sources can be watched individually without approaching the documented monitor-management rate limit. Full discovery/registration/verification is potentially slow and can hit the research paid-call cap; split research into bounded runs. No measured end-to-end timing or live account/rate test was performed. A bulk-watch tool would only remove the watch calls, leaving the main discovery/read/verification costs, so no batch path was added.

Code inspected: `entrypoints/mcp/agent.py`, `entrypoints/mcp/tools/{sources,watching}.py`, `core/services/agents/{briefing,research,service}.py`, `adapters/llm/runtime.py`, `adapters/web/context_dev.py` (under `services/backend/src/ada`).

## Use and deploy

MCP: `watch_source(..., check_every="hourly")`. HTTP: `POST /api/sources/{id}/watch?check_every=hourly`; omit the query parameter to keep the server default. Unsupported values are rejected. Re-watching replaces the monitor; unwatching clears the choice.

Apply migration `0015` with `ada migrate` before deploying the backend/worker, then deploy the frontend. No new environment variables; `CONTEXT_MONITOR_MINUTES` remains the fallback. Existing watch requirements (`CONTEXT_DEV_API_KEY`, `ADA_PUBLIC_URL`, `ADA_SECRET_KEY`) still apply. Existing monitors are not rescheduled by deployment.

## Batch page watching

`watch_sources(project_id, pages=[{url, name, check_every?, provenance?}, ...])` is
available to both agents. HTTP: `POST /api/projects/{project_id}/sources/watch` with
the same list as its JSON body. Accepts 1–50 pages; returns ordered per-page
`url`, `ok`, `source_id` or `error`, and `already_watched`. Existing addresses are
reused, and watched pages keep their monitor and schedule. Repeated URLs within a
batch use the first entry's choices. Concurrent batches serialize the same URL.

Registration uses the existing web/html scrape default, with automatic `page, text`
columns. No initial read, extraction model or pipeline is run, so success confirms
monitor creation, not readability. Change instructions are not supported by the
existing watch path. For structured extraction use the individual source tools.

Four pages run concurrently, each limited to ten seconds, so 50 pages take at most
about 130 seconds; slow pages return an error for a separate retry. A timeout after the
provider created the monitor can leave a remote monitor to delete by hand. Research's
paid-call budget defaults to 80 (`RESEARCH_WEB_CALLS`).
