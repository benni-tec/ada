// TEMPORARY, wave 3: the agent's routes and models, written by hand from
// docs/contracts/wave3.md because the backend that serves them is being built at the same
// time. Integration regenerates the typed client (`moon run frontend:generate`) and moves
// these onto it: the types become `Schemas[...]` names and the calls go through `api`.

import { queryOptions } from '@tanstack/react-query'

import { withLiveParts } from '../agent-turns'
import { ApiFailure, type ApiError } from './client'
import type { DateTime, Id, OperatorId, Schema, Session, SessionEntry } from './models'

/** What a message is about, stored with its entry: chips in the composer. */
export type Context =
  | { kind: 'pipeline'; operator_id: OperatorId }
  | { kind: 'dashboard'; dashboard_id: Id; slot?: string | null }
  | { kind: 'widget'; widget_id: Id }

export type TurnStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

// Parts follow the AI SDK UI message parts, which the shadcn Trace component renders.
export type ReasoningPart = { type: 'reasoning'; text: string }
export type ToolPart = {
  type: 'tool'
  tool_call_id: string
  tool_name: string
  state: 'input-available' | 'output-available' | 'output-error'
  input: Record<string, unknown>
  output: unknown
  error_text: string | null
}
export type TextPart = { type: 'text'; text: string }
export type SourcePart = { type: 'source'; source_id: Id; title: string; url: string | null }
export type Part = ReasoningPart | ToolPart | TextPart | SourcePart

/** One answer of the session's agent: the steps it took and what it said, in order. */
export type AgentTurn = {
  id: Id
  session_id: Id
  prompt_entry_id: Id
  model: string
  status: TurnStatus
  /** Sparse while streaming: a part can arrive before the ones before it. */
  parts: (Part | undefined)[]
  error: string | null
  created_at: DateTime
  finished_at: DateTime | null
}

export type LlmModel = {
  id: string
  provider: string
  model: string
  purposes: string[]
  available: boolean
  /** Why it cannot be used, e.g. its key's variable is not set. */
  reason: string | null
}

/** The models of `llms.yml`; `session_agent` is null when none drives sessions. */
export type LlmModels = { models: LlmModel[]; session_agent: string | null }

/** An operator no other operator reads: the end of a pipeline, what a widget can show. */
export type Pipeline = {
  operator_id: OperatorId
  name: string
  kind: string
  sources: { data_source_id: Id; name: string }[]
  output: Schema
  created_at: DateTime
}

/** The answer to a message: its entry, and the turn queued for the agent (null when no
 * agent is configured, so nobody will answer). */
export type PostedMessage = { entry: SessionEntry; turn: AgentTurn | null }

export type NewMessage = { text: string; context: Context[]; model?: string }

/** A call outside the typed client; an ApiFailure, with the server's detail, otherwise. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Absolute, as in client.ts: Request rejects relative URLs outside a browser (tests).
  const response = await globalThis.fetch(`${window.location.origin}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    const error = data as ApiError | undefined
    throw new ApiFailure(response.status, typeof error?.detail === 'string' ? error : undefined)
  }
  return data as T
}

const path = encodeURIComponent

export const postMessage = (sessionId: Id, message: NewMessage) =>
  call<PostedMessage>('POST', `/api/sessions/${path(sessionId)}/messages`, message)

export const getTurn = (id: Id) => call<AgentTurn>('GET', `/api/turns/${path(id)}`)

export const cancelTurn = (id: Id) => call<unknown>('POST', `/api/turns/${path(id)}/cancel`)

export const listModels = () => call<LlmModels>('GET', '/api/llm/models')

export const listPipelines = (projectId: Id) => call<Pipeline[]>('GET', `/api/projects/${path(projectId)}/pipelines`)

/** The dashboard's agent session, found or created (the agent panel's conversation). */
export const openDashboardAgentSession = (dashboardId: Id) =>
  call<Session>('POST', `/api/dashboards/${path(dashboardId)}/agent-session`)

export const agentKeys = {
  // Not under ['sessions', id]: the record's events would refetch turns mid-stream.
  turn: (id: Id) => ['turns', id] as const,
  models: () => ['llm-models'] as const,
  pipelines: (projectId: Id) => ['projects', projectId, 'pipelines'] as const,
  // Not under ['dashboards', id]: a dashboard event must not post again.
  dashboardSession: (dashboardId: Id) => ['dashboard-agent-session', dashboardId] as const,
}

/** A turn as stored, with the parts the live stream brought since (agent-turns.ts). */
export const turnQuery = (id: Id) =>
  queryOptions({ queryKey: agentKeys.turn(id), queryFn: async () => withLiveParts(await getTurn(id)) })

export const modelsQuery = () =>
  queryOptions({ queryKey: agentKeys.models(), queryFn: listModels, staleTime: 60_000, retry: false })

export const pipelinesQuery = (projectId: Id) =>
  queryOptions({ queryKey: agentKeys.pipelines(projectId), queryFn: () => listPipelines(projectId) })

/** Found or created once per page: asking again would find the same one. */
export const dashboardSessionQuery = (dashboardId: Id) =>
  queryOptions({
    queryKey: agentKeys.dashboardSession(dashboardId),
    queryFn: () => openDashboardAgentSession(dashboardId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
