# Wave 3 contract: the agent in the platform

Shared by the backend and frontend agents of wave 3. Fixed for the wave: if something
here is wrong, report it; do not change it on one side only. Integration folds this file
into `docs/contracts.md`.

## Configuration

- `ADA_LLMS_CONFIG`: path of the models file (default `llms.yml` in the working
  directory). `llms.yml` is git-ignored; `llms.example.yml` at the repo root is committed
  and documents the format. A missing file is not an error: the platform runs without an
  agent and says so.
- Format:

  ```yaml
  providers:
    gemini:
      kind: openai-compatible        # or: gemini (native)
      base_url: https://generativelanguage.googleapis.com/v1beta/openai/
      api_key_env: GEMINI_API_KEY    # name of the environment variable holding the key
  models:
    session_agent: gemini/<model>    # drives sessions and dashboard agent panels
  ```

  Keys are never written into the file and never returned by the API.

## REST (under /api)

| Method and path | Does |
| --- | --- |
| `GET /llm/models` | `{"models": [{"id": "gemini/<model>", "provider": "gemini", "model": "<model>", "purposes": ["session_agent"], "available": true, "reason": null}], "session_agent": "<id or null>"}`; `available` is false, with a `reason`, when the key's variable is not set |
| `POST /sessions/{id}/messages` | Body `{"text": "...", "context": [Context], "model": "<id, optional>"}`. 201 with `{"entry": SessionEntry, "turn": AgentTurn or null}`; `turn` is null when no session agent is configured |
| `GET /sessions/{id}/turns` | The session's agent turns, oldest first |
| `GET /turns/{id}` | One turn |
| `POST /turns/{id}/cancel` | Ask a queued or running turn to stop; 202 |
| `GET /projects/{id}/pipelines` | The project's pipelines (operators that no other operator uses as an input), newest first: `[{"operator_id", "name", "kind", "sources": [{"data_source_id", "name"}], "output": Schema, "created_at"}]` |
| `POST /dashboards/{id}/agent-session` | The dashboard's agent session: the newest session with `origin_dashboard_id` and `panel_dashboard_id` equal to the dashboard, else a new one titled "<dashboard name> (agent)". 200 when found, 201 when created; returns the `Session` |
| `POST /dashboards/{id}/pins` (existing) | Now copies the widget: the dashboard gets a new widget with the same operator, type, spec, title and note, `copied_from` set to the original's id, no `session_id`, created by whoever pins |
| `PUT /dashboards/{id}/slots` (existing) | Layout saves from drag and resize: the full slot list with `expected_revision` |

Context (on a message, stored with its entry):

```
{"kind": "pipeline", "operator_id": "op_..."}
{"kind": "dashboard", "dashboard_id": "...", "slot": "<name, optional>"}
{"kind": "widget", "widget_id": "..."}
```

Model changes: `SessionEntry.context: list[Context]` (empty by default);
`EntryKind.AGENT_TURN = "agent_turn"` (`ref` is the turn id; added when the turn is
queued, so the record orders it after the message); `Widget.copied_from: Id | None`.

AgentTurn:

```
{"id", "session_id", "prompt_entry_id", "model",
 "status": "queued" | "running" | "done" | "failed" | "cancelled",
 "parts": [Part], "error": "<text or null>", "created_at", "finished_at"}
```

Parts follow the AI SDK UI message parts that the shadcn Trace component consumes:

```
{"type": "reasoning", "text": "..."}
{"type": "tool", "tool_call_id": "...", "tool_name": "...",
 "state": "input-available" | "output-available" | "output-error",
 "input": {...}, "output": <json or null>, "error_text": "<text or null>"}
{"type": "text", "text": "..."}
{"type": "source", "source_id": "<data source id>", "title": "...", "url": "<or null>"}
```

Operators and widgets the agent creates through its tools are recorded in the session as
usual (entries of kind `operator` and `widget`), with the actor
`{"kind": "agent", "name": "<model id>"}`.

## Live events

| Event | Payload | When |
| --- | --- | --- |
| `agent.turn_started` | `session_id`, `turn_id` | After the commit that queued or started it |
| `agent.turn_part` | `session_id`, `turn_id`, `index`, `part` | Immediately, not after a commit. The one event that carries content: token deltas cannot be fetched afterwards. A part with the same `index` replaces the earlier one (text grows; a tool's state moves on) |
| `agent.turn_finished` | `session_id`, `turn_id`, `status` | After the commit that stored the final turn |

A client that connects late fetches `GET /turns/{id}` and then applies parts with a
higher index.

## Worker task

`ada.entrypoints.worker.tasks.agent:run_turn(turn_id: str)`.
