// The agent's routes and models (docs/contracts.md, "The agent"), on the typed client.

import { queryOptions } from '@tanstack/react-query'

import { withLiveParts } from '../agent-turns'
import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

/** What a message is about, stored with its entry: chips in the composer. */
export type Context = Schemas['Context']

export type TurnStatus = Schemas['TurnStatus']

// Parts follow the AI SDK UI message parts, which the shadcn Trace component renders.
export type ReasoningPart = Schemas['ReasoningPart']
export type ToolPart = Schemas['ToolPart']
export type TextPart = Schemas['TextPart']
export type SourcePart = Schemas['SourcePart']
export type Part = Schemas['TurnPart']

/** One answer of the session's agent: the steps it took and what it said, in order. */
export type AgentTurn = Omit<Schemas['AgentTurn'], 'parts'> & {
  /** Sparse while streaming: a part can arrive before the ones before it. */
  parts: (Part | undefined)[]
}

export type LlmModel = Schemas['ModelInfo']

/** The models set up in Settings; `session_agent` is null when none drives sessions. */
export type LlmModels = Schemas['ModelList']

/** An operator no other operator reads: the end of a pipeline, what a widget can show. */
export type Pipeline = Schemas['Pipeline']

/** The answer to a message: its entry, and the turn queued for the agent (null when no
 * agent is configured, so nobody will answer). */
export type PostedMessage = Schemas['PostedMessage']

export type NewMessage = Schemas['NewMessage']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

export const postMessage = (sessionId: Id, message: NewMessage) =>
  unwrap(api.POST('/api/sessions/{session_id}/messages', { params: { path: { session_id: sessionId } }, body: message }))

export const getTurn = (id: Id) => unwrap(api.GET('/api/turns/{turn_id}', { params: { path: { turn_id: id } } }))

export const cancelTurn = (id: Id) =>
  unwrap(api.POST('/api/turns/{turn_id}/cancel', { params: { path: { turn_id: id } } }))

export const listModels = () => unwrap(api.GET('/api/llm/models'))

export const listPipelines = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/pipelines', { params: { path: { project_id: projectId } } }))

/** The dashboard's agent session, found or created (the agent panel's conversation). */
export const openDashboardAgentSession = (dashboardId: Id) =>
  unwrap(api.POST('/api/dashboards/{dashboard_id}/agent-session', { params: { path: { dashboard_id: dashboardId } } }))

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
