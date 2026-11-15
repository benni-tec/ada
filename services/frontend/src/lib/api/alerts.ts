// Alert rules, the alert feed and checks (docs/contracts.md, "Alerts"), on the typed client.

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

export type Severity = Schemas['Severity']
export type AlertState = Schemas['AlertState']
export type AlertRule = Schemas['AlertRule']
export type Alert = Schemas['Alert']
export type AlertView = Schemas['AlertView']
export type CheckResult = Schemas['CheckResult']
export type DashboardRules = Schemas['DashboardRules']
export type NewAlertRule = Schemas['NewAlertRule']
export type AlertRuleChange = Schemas['AlertRuleChange']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

/**
 * Query keys of the alert views. Everything sits under ['alerts'] or ['alert-rules'], so a
 * live alert event refetches every view of alerts at once without knowing which dashboard
 * the rule is on (the payload names the alert and the rule only).
 */
export const alertKeys = {
  all: () => ['alerts'] as const,
  feed: (projectId: Id, state: AlertState | null) => ['alerts', 'project', projectId, state ?? 'all'] as const,
  dashboard: (dashboardId: Id) => ['alerts', 'dashboard', dashboardId] as const,
  rules: () => ['alert-rules'] as const,
  projectRules: (projectId: Id) => ['alert-rules', 'project', projectId] as const,
  rule: (id: Id) => ['alert-rules', id] as const,
}

export const listAlerts = (projectId: Id, state: AlertState | null) =>
  unwrap(
    api.GET('/api/projects/{project_id}/alerts', {
      params: { path: { project_id: projectId }, query: state ? { state } : {} },
    }),
  )

export const listDashboardAlerts = (dashboardId: Id, state: AlertState | null) =>
  unwrap(
    api.GET('/api/dashboards/{dashboard_id}/alerts', {
      params: { path: { dashboard_id: dashboardId }, query: state ? { state } : {} },
    }),
  )

export const listProjectAlertRules = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/alert-rules', { params: { path: { project_id: projectId } } }))

export const getAlertRule = (id: Id) =>
  unwrap(api.GET('/api/alert-rules/{rule_id}', { params: { path: { rule_id: id } } }))

export const createAlertRule = (dashboardId: Id, body: NewAlertRule) =>
  unwrap(
    api.POST('/api/dashboards/{dashboard_id}/alert-rules', {
      params: { path: { dashboard_id: dashboardId } },
      body,
    }),
  )

export const updateAlertRule = (id: Id, body: AlertRuleChange) =>
  unwrap(api.PATCH('/api/alert-rules/{rule_id}', { params: { path: { rule_id: id } }, body }))

export const checkAlertRule = (id: Id) =>
  unwrap(api.POST('/api/alert-rules/{rule_id}/check', { params: { path: { rule_id: id } } }))

export const alertFeedQuery = (projectId: Id, state: AlertState | null = null) =>
  queryOptions({ queryKey: alertKeys.feed(projectId, state), queryFn: () => listAlerts(projectId, state) })

export const dashboardAlertsQuery = (dashboardId: Id) =>
  queryOptions({
    queryKey: alertKeys.dashboard(dashboardId),
    queryFn: () => listDashboardAlerts(dashboardId, 'firing'),
  })

export const projectAlertRulesQuery = (projectId: Id) =>
  queryOptions({ queryKey: alertKeys.projectRules(projectId), queryFn: () => listProjectAlertRules(projectId) })

/** The rows that raised the alert: its rule's condition over the measure, in the run that
 * last showed it (the measure's rows for alerts stored before the condition was kept). */
export const alertRowsQuery = (alertId: Id) =>
  queryOptions({
    queryKey: ['alerts', alertId, 'rows'],
    queryFn: () => unwrap(api.GET('/api/alerts/{alert_id}/rows', { params: { path: { alert_id: alertId } } })),
    // A run is a consistent cut: its rows never change, and a new run makes a new alert view.
    staleTime: Infinity,
  })

export const severities: readonly Severity[] = ['critical', 'warning', 'info']


export const deliveriesQuery = (projectId: Id) => queryOptions({
  queryKey: ['alerts', 'deliveries', projectId],
  queryFn: () => unwrap(api.GET('/api/projects/{project_id}/alert-deliveries', { params: { path: { project_id: projectId } } })),
})

export const testAlertRule = (id: Id) => unwrap(api.POST('/api/alert-rules/{rule_id}/test', { params: { path: { rule_id: id } } }))
