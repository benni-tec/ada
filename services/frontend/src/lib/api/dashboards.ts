// Dashboards: the REST calls, the models and the queries. Kept apart from requests.ts and
// queries.ts so the dashboard workstream owns one file here; index.ts re-exports it.

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

// Named with a Dashboard prefix so they never clash with the same words elsewhere.
export type Dashboard = Schemas['Dashboard']
export type DashboardVersion = Schemas['DashboardVersion']
export type DashboardSlot = Schemas['Slot']
export type DashboardTimeRange = Schemas['TimeRange']
export type DashboardRun = Schemas['Run']
/** A dashboard with the version it points at (null before its first edit). The revision
 * for the next write is `dashboard.revision`. */
export type DashboardView = Schemas['DashboardView']

/** The 12-column grid a slot's layout is in; the backend documents the defaults. */
export const GRID_COLUMNS = 12

/** A slot's place on the grid, with the backend's defaults for what is missing. */
export function slotLayout(slot: DashboardSlot) {
  const layout = slot.layout as Partial<Record<'x' | 'y' | 'w' | 'h', unknown>>
  const number = (value: unknown, fallback: number) => (typeof value === 'number' ? value : fallback)
  return { x: number(layout.x, 0), y: number(layout.y, 0), w: number(layout.w, 6), h: number(layout.h, 4) }
}

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

export const listDashboards = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/dashboards', { params: { path: { project_id: projectId } } }))

export const createDashboard = (projectId: Id, name: string) =>
  unwrap(
    api.POST('/api/projects/{project_id}/dashboards', {
      params: { path: { project_id: projectId } },
      body: { name },
    }),
  )

/** Every dashboard of the project, once, in the new order; answers the reordered list. */
export const reorderDashboards = (projectId: Id, ids: Id[]) =>
  unwrap(
    api.PUT('/api/projects/{project_id}/dashboards/order', {
      params: { path: { project_id: projectId } },
      body: { ids },
    }),
  )

export const getDashboard = (id: Id) =>
  unwrap(api.GET('/api/dashboards/{dashboard_id}', { params: { path: { dashboard_id: id } } }))

export const listDashboardVersions = (id: Id) =>
  unwrap(api.GET('/api/dashboards/{dashboard_id}/versions', { params: { path: { dashboard_id: id } } }))

/** Replaces the slots: a new version. `dashboard` is what the edit was made from. */
export const editDashboard = (dashboard: Dashboard, slots: DashboardSlot[]) =>
  unwrap(
    api.PUT('/api/dashboards/{dashboard_id}/slots', {
      params: { path: { dashboard_id: dashboard.id } },
      body: { slots, expected_revision: dashboard.revision },
    }),
  )

/** Puts a widget in a slot, adding the slot when there is none of that name. */
export const pinWidget = (dashboard: Dashboard, widgetId: Id, slot: string) =>
  unwrap(
    api.POST('/api/dashboards/{dashboard_id}/pins', {
      params: { path: { dashboard_id: dashboard.id } },
      body: { widget_id: widgetId, slot, expected_revision: dashboard.revision },
    }),
  )

export const setDefaultTimeRange = (dashboard: Dashboard, range: DashboardTimeRange) =>
  unwrap(
    api.PATCH('/api/dashboards/{dashboard_id}', {
      params: { path: { dashboard_id: dashboard.id } },
      body: { default_time_range: range, expected_revision: dashboard.revision },
    }),
  )

/** One run for the range: the cut every widget on the dashboard reads. */
export const startDashboardRun = (id: Id, range: DashboardTimeRange) =>
  unwrap(
    api.POST('/api/dashboards/{dashboard_id}/runs', {
      params: { path: { dashboard_id: id } },
      body: { time_range: range },
    }),
  )

/** A session that starts from the dashboard and shows it beside the conversation. */
export async function startSessionFromDashboard(projectId: Id, dashboardId: Id, title: string) {
  const session = await unwrap(
    api.POST('/api/projects/{project_id}/sessions', {
      params: { path: { project_id: projectId } },
      body: { title, origin_dashboard_id: dashboardId },
    }),
  )
  await unwrap(
    api.POST('/api/sessions/{session_id}/attachments', {
      params: { path: { session_id: session.id } },
      body: { kind: 'dashboard', ref: dashboardId },
    }),
  )
  return session
}

export const dashboardKeys = {
  list: (projectId: Id) => ['projects', projectId, 'dashboards'] as const,
  view: (id: Id) => ['dashboards', id] as const,
  versions: (id: Id) => ['dashboards', id, 'versions'] as const,
  /** Every dashboard run; a source that changed makes them all stale (see events.ts). */
  allRuns: () => ['dashboard-runs'] as const,
  run: (id: Id, range: DashboardTimeRange) =>
    ['dashboard-runs', id, range.start ?? null, range.end ?? null] as const,
}

export const dashboardsQuery = (projectId: Id) =>
  queryOptions({ queryKey: dashboardKeys.list(projectId), queryFn: () => listDashboards(projectId) })

export const dashboardQuery = (id: Id) =>
  queryOptions({ queryKey: dashboardKeys.view(id), queryFn: () => getDashboard(id) })

export const dashboardVersionsQuery = (id: Id) =>
  queryOptions({ queryKey: dashboardKeys.versions(id), queryFn: () => listDashboardVersions(id) })

/**
 * The run a dashboard is viewed at. It is started once per range and kept: starting one
 * is a write, so it must not repeat when the page is focused or remounted. It becomes
 * stale only when the data changes, which starts a new run.
 */
export const dashboardRunQuery = (id: Id, range: DashboardTimeRange) =>
  queryOptions({
    queryKey: dashboardKeys.run(id, range),
    queryFn: () => startDashboardRun(id, range),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
