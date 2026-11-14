// Runs: starting the run a page is viewed at, and reading an operator's output and the
// snapshots a run fixed (docs/contracts.md, "REST").

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id, OperatorId } from './models'
import { keys } from './queries'

export type Run = Schemas['Run']
export type Rows = Schemas['Rows']
export type Snapshot = Schemas['Snapshot']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

/** A run over the whole of every source: what widgets outside a dashboard show. */
export const startProjectRun = (projectId: Id) =>
  unwrap(api.POST('/api/projects/{project_id}/runs', { params: { path: { project_id: projectId } }, body: {} }))

export const getRun = (id: Id) => unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: id } } }))

export const readOperatorRows = (runId: Id, operatorId: OperatorId, limit: number) =>
  unwrap(
    api.GET('/api/runs/{run_id}/operators/{operator_id}/rows', {
      params: { path: { run_id: runId, operator_id: operatorId }, query: { limit } },
    }),
  )

export const getSnapshot = (id: Id) =>
  unwrap(api.GET('/api/snapshots/{snapshot_id}', { params: { path: { snapshot_id: id } } }))

export const runKeys = {
  /** Every run a page is viewed at but a dashboard's (those are under dashboardKeys). */
  views: () => ['view-runs'] as const,
  projectView: (projectId: Id) => ['view-runs', 'project', projectId] as const,
  // Not under ['runs', id]: the run's events would refetch rows that cannot change.
  rows: (runId: Id, operatorId: OperatorId, limit: number) => ['run-rows', runId, operatorId, limit] as const,
  snapshot: (id: Id) => ['snapshots', id] as const,
}

/**
 * The run a session or a widget page is viewed at: every widget card on it reads this one.
 * Started once and kept, like a dashboard's (dashboardRunQuery): starting a run is a write,
 * so it must not repeat on focus or remount. Changed data makes it stale (useViewRun).
 */
export const projectRunQuery = (projectId: Id) =>
  queryOptions({
    queryKey: runKeys.projectView(projectId),
    queryFn: () => startProjectRun(projectId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

/** A run as stored: which snapshot it fixed for each materializing operator. It gains
 * snapshots while its widgets execute; the run's live events refetch it (events.ts). */
export const runQuery = (id: Id) => queryOptions({ queryKey: keys.run(id), queryFn: () => getRun(id) })

export const operatorRowsQuery = (runId: Id, operatorId: OperatorId, limit: number) =>
  queryOptions({
    queryKey: runKeys.rows(runId, operatorId, limit),
    queryFn: () => readOperatorRows(runId, operatorId, limit),
    // A run is a consistent cut: an operator's output in it never changes.
    staleTime: Infinity,
  })

export const snapshotQuery = (id: Id) =>
  queryOptions({
    queryKey: runKeys.snapshot(id),
    queryFn: () => getSnapshot(id),
    // Snapshots are written once and never changed.
    staleTime: Infinity,
  })
