// Reports, their versions and sources lists, and templates (docs/contracts.md, "Reports").

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id, OperatorId } from './models'

export type Report = Schemas['Report']
export type ReportVersion = Schemas['ReportVersion']
export type ReportSource = Schemas['ReportSource']
export type Template = Schemas['Template']
export type Slot = Schemas['Slot']
export type TimeRange = Schemas['TimeRange']
export type VersionBump = Schemas['VersionBump']

// The component tree of a version's content (core/services/reports/content.py).

export type HeadingBlock = { type: 'heading'; text: string; level: 1 | 2 | 3 }
export type TextBlock = { type: 'text'; text: string }
export type CalloutBlock = { type: 'callout'; tone: 'note' | 'finding' | 'warning'; title: string; text: string }
export type WidgetBlock = { type: 'widget'; widget_id: Id; caption: string }
export type SectionBlock = { type: 'section'; title: string; blocks: Block[] }
export type Block = HeadingBlock | TextBlock | CalloutBlock | WidgetBlock | SectionBlock

/** The blocks of a stored version. The server checked the tree when it was written; this
 * only gives it a type, and drops what this frontend cannot draw rather than failing. */
export function blocksOf(version: ReportVersion): Block[] {
  const blocks = version.content.blocks
  return Array.isArray(blocks) ? blocks.filter(isBlock) : []
}

function isBlock(value: unknown): value is Block {
  if (typeof value !== 'object' || value === null) return false
  const type = (value as { type?: unknown }).type
  return type === 'heading' || type === 'text' || type === 'callout' || type === 'widget' || type === 'section'
}

/** The widgets a version shows, in reading order, each once. */
export function widgetIdsOf(blocks: Block[]): Id[] {
  const ids: Id[] = []
  const visit = (items: Block[]) => {
    for (const block of items) {
      if (block.type === 'widget' && !ids.includes(block.widget_id)) ids.push(block.widget_id)
      if (block.type === 'section') visit(block.blocks)
    }
  }
  visit(blocks)
  return ids
}

/** Versions as numbers, so 1.10.0 sorts after 1.9.0. */
export function compareVersions(a: string, b: string): number {
  const left = a.split('.').map(Number)
  const right = b.split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    const difference = (left[i] ?? 0) - (right[i] ?? 0)
    if (difference !== 0) return difference
  }
  return 0
}

export function describeTimeRange(range: TimeRange): string {
  if (!range.start && !range.end) return 'All periods'
  return `${range.start ?? 'the beginning'} – ${range.end ?? 'now'}`
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

// Requests

export const listReports = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/reports', { params: { path: { project_id: projectId } } }))

/** Every report of the project, once, in the new order; answers the reordered list. */
export const reorderReports = (projectId: Id, ids: Id[]) =>
  unwrap(
    api.PUT('/api/projects/{project_id}/reports/order', {
      params: { path: { project_id: projectId } },
      body: { ids },
    }),
  )

export const getReport = (id: Id) =>
  unwrap(api.GET('/api/reports/{report_id}', { params: { path: { report_id: id } } }))

export const listReportVersions = (id: Id) =>
  unwrap(api.GET('/api/reports/{report_id}/versions', { params: { path: { report_id: id } } }))

export const listReportSources = (versionId: Id) =>
  unwrap(api.GET('/api/report-versions/{version_id}/sources', { params: { path: { version_id: versionId } } }))

export const generateReport = (dashboardId: Id, name: string) =>
  unwrap(
    api.POST('/api/dashboards/{dashboard_id}/reports', {
      params: { path: { dashboard_id: dashboardId } },
      body: { name },
    }),
  )

export const getTemplate = (id: Id) =>
  unwrap(api.GET('/api/templates/{template_id}', { params: { path: { template_id: id } } }))

export const getLineage = (operatorId: OperatorId) =>
  unwrap(api.GET('/api/operators/{operator_id}/lineage', { params: { path: { operator_id: operatorId } } }))

// Queries. The keys sit under the prefixes of ./queries.ts: a project's reports under
// ['projects', id], a report's versions under ['reports', id].

export const reportKeys = {
  reports: (projectId: Id) => ['projects', projectId, 'reports'] as const,
  report: (id: Id) => ['reports', id] as const,
  versions: (id: Id) => ['reports', id, 'versions'] as const,
  sources: (versionId: Id) => ['report-versions', versionId, 'sources'] as const,
  template: (id: Id) => ['templates', id] as const,
  lineage: (operatorId: OperatorId) => ['operators', operatorId, 'lineage'] as const,
}

export const reportsQuery = (projectId: Id) =>
  queryOptions({ queryKey: reportKeys.reports(projectId), queryFn: () => listReports(projectId) })

export const reportQuery = (id: Id) => queryOptions({ queryKey: reportKeys.report(id), queryFn: () => getReport(id) })

export const reportVersionsQuery = (id: Id) =>
  queryOptions({ queryKey: reportKeys.versions(id), queryFn: () => listReportVersions(id) })

export const reportSourcesQuery = (versionId: Id) =>
  queryOptions({
    queryKey: reportKeys.sources(versionId),
    queryFn: () => listReportSources(versionId),
    // A version never changes, and neither does what it was generated from.
    staleTime: Infinity,
  })

export const templateQuery = (id: Id) =>
  queryOptions({ queryKey: reportKeys.template(id), queryFn: () => getTemplate(id), staleTime: Infinity })

export const lineageQuery = (operatorId: OperatorId) =>
  queryOptions({
    queryKey: reportKeys.lineage(operatorId),
    queryFn: () => getLineage(operatorId),
    // An operator's id is its identity: its pipeline is always the same.
    staleTime: Infinity,
  })
