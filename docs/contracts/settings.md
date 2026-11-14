# Contract: the settings page (agents and data sources)

Decided with the user:

- The agent is configured in the platform, not in a file. `llms.yml`, `llms.example.yml`,
  `ADA_LLMS_CONFIG`, the `config/` mount and the YAML loader go away.
- Providers, their API keys and which model runs sessions are **shared by all projects**
  (one ADA instance, one set of keys). Data sources stay per project.
- API keys are stored **encrypted in the database**. The master key comes from
  `ADA_SECRET_KEY` (a Fernet key, urlsafe base64 of 32 bytes), or from the file named by
  `ADA_SECRET_KEY_FILE` (Docker secrets). Neither set: the platform runs, but a key cannot
  be stored (the API says so with a 409 and a clear detail; the page shows why). A key
  that cannot be decrypted (master key changed or lost) makes its provider's models
  unavailable with the reason "The stored key cannot be decrypted; enter it again".
- In development, `moon run :dev` makes sure `.env.local` has an `ADA_SECRET_KEY`: a
  small script generates one when it is missing (never overwrites). Compose passes
  `.env.local` already (`env_file`, `required: false`).
- The settings page is reached from the **bottom of the project sidebar** (a gear,
  "Settings", in the sidebar footer). Route `/projects/$projectId/settings`.

## Backend

- `cryptography` (Fernet) behind a port `SecretBox` (`core/ports/secrets.py`):
  `available: bool`, `encrypt(text) -> str`, `decrypt(token) -> str` (raises
  `SecretUnreadable`). Adapter `adapters/secrets/fernet.py`; `MultiFernet` so
  `ADA_SECRET_KEY` may hold several comma-separated keys, the first encrypting (rotation).
- Models (`core/models/agents.py`):
  - `ProviderKind`: `openai-compatible` | `gemini` (moved from the YAML loader).
  - `LlmProvider {id, name, kind, base_url, has_api_key, created_at, revision}`. `name`
    is a slug (`[a-z0-9-]+`), unique; it is the first half of a model id. The key is
    never part of the model or any response.
  - `LlmModel {id: "<provider name>/<model>", provider_id, model, created_at}`.
  - `ModelInfo` / `ModelList` stay as they are (`GET /llm/models` keeps its shape);
    `purposes` holds `session_agent` for the one session agent.
  - `ModelTarget {model_id, kind, base_url, model, api_key: SecretStr | None}`: what the
    runtime needs to call one model. `TurnRequest` gains `target: ModelTarget`.
- Tables (migration `0005`): `llm_providers` (`id`, `name` unique, `kind`, `base_url`,
  `api_key_encrypted` text null, `created_at`, `revision`), `llm_models` (`id` uuid,
  `provider_id` → providers `CASCADE`, `model`, `created_at`, unique `(provider_id,
  model)`), `agent_settings` (one row: `session_agent_model_id` → `llm_models` `SET NULL`,
  `revision`).
- `AgentSettingsService` (`core/services/agents/settings.py`, inbound port in
  `core/services/ports/agents.py`), which also implements the `LanguageModels` port, now
  async: `catalog() -> ModelList`, `target(model_id) -> ModelTarget` (raises Invalid with
  the reason when the model is unknown or unavailable).
  - Availability: a `gemini` provider needs a key; an `openai-compatible` one works
    without (e.g. local vLLM). Unreadable key → unavailable with the reason above.
  - Changing a key never needs the old one; `api_key: ""`/`null` in a change clears it.
- REST (tag `settings`), all instance-wide:
  - `GET /settings/agent` → `{providers: LlmProvider[], models: ModelList, session_agent:
    string|null, secrets_available: bool, revision}`
  - `POST /settings/llm-providers {name, kind, base_url?, api_key?}` → 201 provider
  - `PATCH /settings/llm-providers/{id} {expected_revision, name?, kind?, base_url?,
    api_key?}` → provider (409 on a stale revision)
  - `DELETE /settings/llm-providers/{id}` → 204 (its models go with it; the session agent
    is cleared if it was one of them)
  - `POST /settings/llm-models {provider_id, model}` → 201 `ModelInfo`
  - `DELETE /settings/llm-models/{id}` → 204 (`id` is the `"<provider>/<model>"` string,
    URL-encoded)
  - `PUT /settings/session-agent {model_id: string|null, expected_revision}` → the
    `GET /settings/agent` body
  - `GET /llm/models` unchanged in shape, now from the database.
- The runtime takes the target from the request (`PydanticAiRuntime()` without config;
  `model_factory` for tests stays). `AgentTurns` asks `LanguageModels` (async) for the
  catalog when a message is posted and for the target when the turn runs.
- Data sources: no backend change needed (list, register, update, refresh exist).
- MCP: no settings tools (keys must not pass through agents).

## Frontend

- Sidebar footer: "Settings" with a gear icon (tooltip when collapsed), active on the
  settings route.
- `/projects/$projectId/settings`, type label "Settings", two sections:
  - **Agents** (says "Shared by all projects"): the session agent picker (models from the
    catalog, unavailable ones disabled with their reason); providers as cards (name,
    kind, base URL, key status "Key stored" / "No key", edit, delete with confirm); per
    provider its models with add (model name input) and delete; "Add provider" form
    (name, kind select, base URL, API key as a password field that is never prefilled).
    When `secrets_available` is false: a notice that `ADA_SECRET_KEY` is not set and keys
    cannot be stored, key fields disabled.
  - **Data sources** (this project): the list with name, access kind, format, address,
    freshness, last refresh / last error; add (name, access kind, address, format,
    freshness), edit (same fields, `expected_revision`, 409 handled), refresh now.
- The chat's "no agent configured" note points to Settings (a link), not to `llms.yml`.
- Icons with tooltips for icon-only actions (edit = pencil, delete = trash, refresh).

## Not in this step

Per-project agent settings, deleting data sources, MCP tools for settings, key rotation UI.
