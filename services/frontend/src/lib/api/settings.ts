// TEMPORARY, settings page: the instance-wide agent settings (providers, their keys, models
// and the session agent), written by hand from docs/contracts/settings.md because the
// backend that serves them is being built at the same time. Integration regenerates the
// typed client (`moon run frontend:generate`) and moves these onto it: the types become
// `Schemas[...]` names and the calls go through `api`.

import { queryOptions } from '@tanstack/react-query'

import { ApiFailure, type ApiError } from './client'
import type { LlmModel, LlmModels } from './agent'
import type { DateTime, Id } from './models'

export type ProviderKind = 'openai-compatible' | 'gemini'

/** A provider of models. Its key is never sent back, only whether one is stored. */
export type LlmProvider = {
  id: Id
  /** A slug (`[a-z0-9-]+`), unique: the first half of its models' ids. */
  name: string
  kind: ProviderKind
  base_url: string | null
  has_api_key: boolean
  created_at: DateTime
  revision: number
}

/** Shared by all projects: one set of providers and keys, one session agent. */
export type AgentSettings = {
  providers: LlmProvider[]
  models: LlmModels
  session_agent: string | null
  /** False when `ADA_SECRET_KEY` is not set: no key can be stored. */
  secrets_available: boolean
  revision: number
}

export type NewProvider = {
  name: string
  kind: ProviderKind
  base_url?: string | null
  api_key?: string | null
}

/** `api_key` left out keeps the stored key; `""` or null clears it. */
export type ProviderChange = {
  expected_revision: number
  name?: string
  kind?: ProviderKind
  base_url?: string | null
  api_key?: string | null
}

/** A call outside the typed client; an ApiFailure, with the server's detail, otherwise. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Absolute, as in client.ts: Request rejects relative URLs outside a browser (tests).
  const response = await globalThis.fetch(`${window.location.origin}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined)
  if (!response.ok) {
    const error = data as ApiError | undefined
    throw new ApiFailure(response.status, typeof error?.detail === 'string' ? error : undefined)
  }
  return data as T
}

const path = encodeURIComponent

export const getAgentSettings = () => call<AgentSettings>('GET', '/api/settings/agent')

export const createProvider = (provider: NewProvider) => call<LlmProvider>('POST', '/api/settings/llm-providers', provider)

export const updateProvider = (id: Id, change: ProviderChange) =>
  call<LlmProvider>('PATCH', `/api/settings/llm-providers/${path(id)}`, change)

export const deleteProvider = (id: Id) => call<void>('DELETE', `/api/settings/llm-providers/${path(id)}`)

export const addModel = (providerId: Id, model: string) =>
  call<LlmModel>('POST', '/api/settings/llm-models', { provider_id: providerId, model })

/** `id` is the model's `"<provider>/<model>"`. */
export const deleteModel = (id: string) => call<void>('DELETE', `/api/settings/llm-models/${path(id)}`)

export const setSessionAgent = (modelId: string | null, expectedRevision: number) =>
  call<AgentSettings>('PUT', '/api/settings/session-agent', { model_id: modelId, expected_revision: expectedRevision })

export const settingsKeys = {
  agent: () => ['settings', 'agent'] as const,
}

export const agentSettingsQuery = () => queryOptions({ queryKey: settingsKeys.agent(), queryFn: getAgentSettings })
