# Wave 3, backend: what was built

The backend half of `docs/contracts/wave3.md`. Integration folds both into
`docs/contracts.md`; this file says where things live, what was decided on the way, and
what is still open.

## Where things live

| Part | Where |
| --- | --- |
| Models | `core/models/agents.py` (`ModelInfo`, `ModelList`, `AgentTurn`, `TurnStatus`, the parts, `PostedMessage`, `TurnRequest`, `HistoryMessage`, `ToolSpec`), `core/models/pipelines.py` (`Pipeline`, `PipelineSource`), `core/models/sessions.py` (`PipelineContext`, `DashboardContext`, `WidgetContext`, `Context`, `EntryKind.AGENT_TURN`, `SessionEntry.context`), `Widget.copied_from`, the three `agent.turn_*` event types |
| Outbound ports | `core/ports/agents.py`: `LanguageModels` (the models file), `AgentRuntime` (runs a model with tools), `AgentTools` / `AgentToolbox` (the tools of a turn), `TurnSink` (where a running turn reports parts), `TurnProgress` (a running turn's writes, each committed at once), `AgentFailed`, `ToolCallFailed`. `AgentTurnRepository` in `core/ports/repositories.py`; `TaskDispatcher.run_turn` |
| Inbound ports | `core/services/ports/agents.py`: `AgentTurnService` (`models`, `post_message`, `turns`, `get`, `cancel`, `run`). `SessionService.add_message(..., context)`, `record_agent_turn`, `dashboard_agent_session`; `PipelineService.pipelines` |
| Services | `core/services/agents/service.py` (`AgentTurns`), `core/services/agents/briefing.py` (system prompt and history), `core/services/pipelines/listing.py` (roots and readable names), copy on pin in `core/services/dashboards/service.py` |
| Adapters | `adapters/llm/config.py` (the models file), `adapters/llm/runtime.py` (`PydanticAiRuntime`), `adapters/db/agent_repositories.py` (`SqlAgentTurnRepository`, `SqlTurnProgress`), memory equivalents in `adapters/memory/repositories.py` |
| Bindings | `composition/providers/agents.py` (models file, runtime, `AgentTurnService`); repositories and `TurnProgress` in `providers/repositories.py` |
| Entrypoints | `routers/agents.py` (`/llm/models`, turns, cancel), `POST /sessions/{id}/messages` in `routers/sessions.py`, `/projects/{id}/pipelines` in `routers/operators.py`, `/dashboards/{id}/agent-session` in `routers/dashboards.py`; MCP `list_pipelines` in `mcp/tools/pipelines.py`; `mcp/agent.py` (`InProcessToolbox`); `mcp/actor.py` (`acting_as`); worker task `worker/tasks/agent.py:run_turn` |
| Migration | `0003`: `session_entries.context` (JSONB, default `[]`), `widgets.copied_from` (FK to widgets, `SET NULL`), table `agent_turns` (with `cancel_requested`) |
| Configuration | `Settings.llms_config` from `ADA_LLMS_CONFIG` (default `llms.yml`); `llms.example.yml` at the root; `config/llms.yml` is where moon and compose look |

## How a turn runs

1. **Posting.** `POST /sessions/{id}/messages` calls `AgentTurnService.post_message` in one
   unit of work: the message entry with its checked context; when the models file names a
   session agent (or the body names another configured `model`), an `AgentTurn` (queued)
   and an `agent_turn` entry by `{"kind": "agent", "name": <model id>}`; `agent.turn_started`
   and the task after the commit. An unknown `model` is 422 and nothing is stored. A
   configured model whose key is not set gives a turn that is `failed` at once with the
   reason ("The environment variable GEMINI_API_KEY is not set"), and no task.
2. **The task.** `run_turn(turn_id)` resolves the application's container (the parent of
   the task's request container) and calls `AgentTurnService.run(turn_id,
   InProcessToolbox(container))`. It never raises: everything is caught and logged.
3. **Starting.** `TurnProgress.start` moves queued to running in its own transaction (a
   turn cancelled while queued is skipped), then `agent.turn_started` is broadcast.
4. **The request.** `Briefing` builds the system prompt (what ADA is, the project and
   session with ids, the panel and origin dashboards, the rules from the plan, and each
   context item explained: a pipeline to build on with its name and columns, a dashboard
   and slot to pin to, a widget referred to), the history (earlier messages; earlier
   answers as their text plus one line per tool call naming what it made, a line per
   source read, and a note when they failed or were cancelled; operators and widgets that
   other clients recorded, as notes), at most the last 40 messages.
5. **Tools.** `InProcessToolbox.connect` sets the agent's actor in a context variable, then
   opens FastMCP's in-memory client on `create_mcp(container)`. Every tool call is a unit
   of work of its own, exactly as over HTTP, so entries and widgets appear in the session
   as they are made. `get_widget_data`, `create_project` and `create_session` are left
   out. When a tool takes `session_id` and the model leaves it out, the turn's session is
   filled in. A tool error comes back as `ToolCallFailed`, which the runtime hands to the
   model as a retry (`ModelRetry`).
6. **Running.** `PydanticAiRuntime` builds an `Agent` per turn (`output_type=str`, the
   tools as `Tool.from_schema(..., sequential=True)`, tool retries 3), runs `agent.iter`
   with `instructions`, the history and `UsageLimits(request_limit=24)`, streams each
   model request and each tool step, and calls `TurnSink.checkpoint()` between steps.
7. **Parts.** Text and thinking parts are added when they first have text and replaced as
   deltas arrive; a tool part is added at `FunctionToolCallEvent` (`input-available`, the
   full arguments) and replaced at its result (`output-available` with the JSON result, or
   `output-error` with the message). After a successful tool result, every source
   operator in it (`add_source_operator`, `get_lineage`) adds a `source` part, once per
   data source per turn, with the source's name and its address when that is a URL. Every
   change is broadcast at once as `agent.turn_part` (`index`, the whole part).
8. **Checkpoints.** After each step the parts so far are stored (`TurnProgress.checkpoint`,
   own transaction), which also reads the cancel flag.
9. **The end.** `TurnProgress.finish` stores status, parts, error and `finished_at`; then
   `agent.turn_finished` with the status is broadcast.

## Decisions

- **The agent's actor comes from the worker's context, not from a client name.**
  `acting_as(agent)` sets a context variable before the in-memory client starts its
  server; the server's tasks inherit it, so `calling_agent()` returns `Actor(agent, <model
  id>)`. A client over HTTP runs in the HTTP server's tasks, which never see it: whatever
  name it reports (including the in-process client's), it is `external_agent`. The
  in-process client's name (`ada-in-platform-agent`) is only for logs.
- **A running turn writes through `TurnProgress`, not the task's transaction.** A turn runs
  for minutes; written in the task's unit of work, its parts would stay invisible until
  the end and its row locked, so a cancel request would wait for the turn it means to
  stop. `SqlTurnProgress` opens a short transaction per write on the engine, like
  `SqlSourceCheckLog`. The started and finished events are broadcast right after those
  commits ("after the commit that started / stored it"), parts at once (the contract's
  exception). `AgentTurns` is therefore the one service that holds the `EventBroadcaster`.
- **Turn writes are plain UPDATEs of their own columns**, without a revision: the worker is
  the only writer of status and parts, a cancel request writes `cancel_requested` (and,
  for a queued turn, the status, in one conditional statement), so neither overwrites the
  other and a cancel racing a start is decided by the database.
- **`agent.turn_started` is published twice**: when the turn is queued (after the message's
  commit) and when the worker starts it. Both carry only ids; a client refetches the turn.
- **Cancelling** a queued turn ends it at once (`cancelled`, `finished_at`,
  `agent.turn_finished` after the commit); a running one is flagged and stops at its next
  checkpoint; a finished one is returned unchanged. All answer 202 with the turn.
- **Failures are readable.** `AgentFailed` messages: "The agent did not finish within 24
  steps", "The model provider refused the key: …", "… could not be reached: …", "…
  answered with an error: …", "The model did not answer as expected: …" (e.g. a tool that
  kept refusing beyond the retries). Anything else becomes "The turn failed unexpectedly:
  <type>: <message>" and is logged with its traceback. If queueing the task fails after
  the commit, the turn is marked failed ("The turn could not be queued: …").
- **The models file** is validated with pydantic (unknown keys are errors, an
  `openai-compatible` provider needs `base_url`, every model names a configured provider,
  purposes are known); every problem is named with its path. The API's lifespan and the
  worker's startup resolve `LanguageModels`, so a broken file stops them at start. A
  missing file is an empty catalog. Keys are read once per process from the variables the
  file names; `api_key_env` may be left out for an endpoint without a key. The model id is
  split at the first slash, so model names may contain slashes.
- **Gemini natively** (`kind: gemini`) uses pydantic-ai's `GoogleModel`; the dependency is
  `pydantic-ai-slim[openai,google]`, not the full `pydantic-ai`, to keep the image small.
- **Copy on pin.** `copied_from` is the original made in a session: pinning a copy again
  copies its `copied_from`, so one step always leads back to the session. The copy is
  announced with `widget.created` (no `session_id`). A stale `expected_revision` is refused
  before the copy is made.
- **Pipelines** are named by the source's name, a transform's leading `--` comment lines
  (joined), else its whitespace-collapsed SQL, cut at 60 characters with "…", and an
  input's slot name. Sources are listed once each, inputs first, so a diamond lists its
  source once.
- **Dashboard agent session.** `SessionService.dashboard_agent_session` returns
  `(session, created)`; the route answers 200 or 201. The session is announced with
  `session.created`.
- **Tests never read the developer's models file**: `tests/conftest.py` points
  `ADA_LLMS_CONFIG` at a file that does not exist. The agent tests use pydantic-ai's
  `FunctionModel` (`tests/agent_support.py`: a scripted model, steps that call tools or
  stream text); one test uses a real OpenAI client against `127.0.0.1:1` with retries off,
  to check the unreachable-provider path without any network.

## Deviations from the contract

None in routes, payloads or events. Additions the contract leaves open:

- `ModelInfo`, `AgentTurn` and the parts are exactly the contract's shapes; `PostedMessage`
  is `{"entry", "turn"}`.
- `POST /turns/{id}/cancel` returns the turn (202).
- `agent.turn_started` is sent when queued and again when started (see above).
- The pipelines list follows the contract to the letter: an alert rule's condition (a
  pass-through transform the platform adds) is a root too, and is listed. Hiding operators
  made by `system` actors may be wanted; that would change the contract.

## What integration must do

- Fold this file and `wave3.md` into `docs/contracts.md`: the new routes, tools, events,
  task, ports and bindings tables (`agents.py` provider; thirteen repositories plus
  `TurnProgress`), `tach.toml` (services' inbound ports may name outbound ports; the
  worker depends on `ada.entrypoints.mcp`), the configuration table (`ADA_LLMS_CONFIG`),
  and the known issues below.
- Regenerate the frontend's API types (`moon run frontend:generate`) after merging both
  sides: `POST /sessions/{id}/messages` now answers `{entry, turn}`, and there are new
  routes and fields.
- The MCP tool table gains `list_pipelines`; `pin_widget`'s description says it copies.
- Build new images (`moon run :image`) so the full stack has the agent; compose now mounts
  `./config` and reads `.env.local` (both optional).

## Known issues

- **The task's own transaction stays open during a turn.** `run_turn` reads the turn, the
  session and its record through the task's request scope, which keeps one pooled
  connection idle in a transaction until the turn ends (minutes). Harmless for
  correctness (no locks beyond reads); splitting the reads into a scope of their own would
  free it.
- **A worker killed mid-turn leaves the turn `running`.** Cancellation by the process
  (`CancelledError`) is not caught, and nothing sweeps stale running turns. A sweep (e.g.
  running turns with no checkpoint for some minutes become failed) would fix it.
- **Two messages in quick succession run two turns at once**, each with the history it
  found; the second does not wait for the first's answer.
- **History is bounded by count (40 messages), not by tokens**, and tool results are given
  to the model in full (a long `get_lineage` costs tokens). Earlier answers keep only a
  one-line summary per tool call.
- **Token deltas are broadcast one event each.** Fine for a demo; a busy model may want
  them batched.
- **Source parts come only from source operators in tool results** (`add_source_operator`,
  `get_lineage`); reading a pipeline's data through `preview_operator` does not add one.
- **The pipelines list includes alert conditions** (see Deviations).
- **The models file is read once per process.** Changing it or a key means restarting the
  backend and the worker.
