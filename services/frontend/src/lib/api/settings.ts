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

export const setResearchAgent = (modelId: string | null, expectedRevision: number) =>
  unwrap(api.PUT('/api/settings/research-agent', { body: { model_id: modelId, expected_revision: expectedRevision } }))

/** The session agent's instructions for every project; shares the settings' revision. */
export const setAgentInstructions = (instructions: string, expectedRevision: number) =>
  unwrap(api.PUT('/api/settings/agent-instructions', { body: { instructions, expected_revision: expectedRevision } }))

/** Whether a Context.dev key is set, and the daily credit budget per project (read only). */
export type WebSettings = Schemas['WebSettings']
export const getWebSettings = () => unwrap(api.GET('/api/settings/web'))

/** The session agent's instructions for this project ("" for none). */
export const setProjectInstructions = (projectId: Id, instructions: string, expectedRevision: number) =>
  unwrap(
    api.PATCH('/api/projects/{project_id}', {
      params: { path: { project_id: projectId } },
      body: { agent_instructions: instructions, expected_revision: expectedRevision },
    }),
  )

/** What `POST /projects/{id}/files` answers: the address a document source reads it from. */
export type StoredFile = Schemas['StoredFile']

/** Uploads a file as the raw body; the schema describes no body, so this is plain fetch. */
export async function uploadFile(projectId: Id, file: File): Promise<StoredFile> {
  const url = new URL(`/api/projects/${encodeURIComponent(projectId)}/files`, window.location.origin)
  url.searchParams.set('filename', file.name)
  const response = await globalThis.fetch(
    new Request(url, { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } }),
  )
  const body: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const error = body as ApiError | undefined
    throw new ApiFailure(response.status, typeof error?.detail === 'string' ? error : undefined)
  }
  return body as StoredFile
}

export const settingsKeys = {
  agent: () => ['settings', 'agent'] as const,
  web: () => ['settings', 'web'] as const,
}

export const agentSettingsQuery = () => queryOptions({ queryKey: settingsKeys.agent(), queryFn: getAgentSettings })

export const webSettingsQuery = () => queryOptions({ queryKey: settingsKeys.web(), queryFn: getWebSettings })
