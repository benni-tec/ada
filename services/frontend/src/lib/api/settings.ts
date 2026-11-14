// The instance-wide agent settings (providers, their keys, models and the session agent),
// on the typed client (docs/contracts.md, "The agent").

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

export type ProviderKind = Schemas['ProviderKind']
/** A provider of models. Its key is never sent back, only whether one is stored. */
export type LlmProvider = Schemas['LlmProvider']
/** Shared by all projects: one set of providers and keys, one session agent. */
export type AgentSettings = Schemas['AgentSettingsView']
export type NewProvider = Schemas['NewProvider']
/** `api_key` left out keeps the stored key; `""` or null clears it. */
export type ProviderChange = Schemas['ProviderChange']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  // A 204 has no body.
  if (!response.ok || (data === undefined && response.status !== 204)) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data as T
}

export const getAgentSettings = () => unwrap(api.GET('/api/settings/agent'))

export const createProvider = (provider: NewProvider) => unwrap(api.POST('/api/settings/llm-providers', { body: provider }))

export const updateProvider = (id: Id, change: ProviderChange) =>
  unwrap(api.PATCH('/api/settings/llm-providers/{provider_id}', { params: { path: { provider_id: id } }, body: change }))

export const deleteProvider = (id: Id) =>
  unwrap(api.DELETE('/api/settings/llm-providers/{provider_id}', { params: { path: { provider_id: id } } }))

export const addModel = (providerId: Id, model: string) =>
  unwrap(api.POST('/api/settings/llm-models', { body: { provider_id: providerId, model } }))

/** `id` is the model's `"<provider>/<model>"`. */
export const deleteModel = (id: string) =>
  unwrap(api.DELETE('/api/settings/llm-models/{model_id}', { params: { path: { model_id: id } } }))

export const setSessionAgent = (modelId: string | null, expectedRevision: number) =>
  unwrap(api.PUT('/api/settings/session-agent', { body: { model_id: modelId, expected_revision: expectedRevision } }))

export const settingsKeys = {
  agent: () => ['settings', 'agent'] as const,
}

export const agentSettingsQuery = () => queryOptions({ queryKey: settingsKeys.agent(), queryFn: getAgentSettings })
