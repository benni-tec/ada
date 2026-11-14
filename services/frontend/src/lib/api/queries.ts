import { queryOptions } from '@tanstack/react-query'

import type { Id } from './models'
import {
  getOperator,
  getProject,
  getSession,
  getWidget,
  listEntries,
  listProjects,
  listProjectWidgets,
  listSessions,
  listSessionWidgets,
  listSources,
} from './requests'

/**
 * Query keys, shaped so that invalidating a prefix covers what belongs to it: a
 * project's sources and sessions sit under ['projects', id], a session's entries and
 * widgets under ['sessions', id]. The live events (../events.ts) invalidate by these.
 */
export const keys = {
  projects: () => ['projects'] as const,
  project: (id: Id) => ['projects', id] as const,
  sources: (projectId: Id) => ['projects', projectId, 'sources'] as const,
  source: (id: Id) => ['sources', id] as const,
  sessions: (projectId: Id) => ['projects', projectId, 'sessions'] as const,
  projectWidgets: (projectId: Id) => ['projects', projectId, 'widgets'] as const,
  session: (id: Id) => ['sessions', id] as const,
  entries: (sessionId: Id) => ['sessions', sessionId, 'entries'] as const,
  sessionWidgets: (sessionId: Id) => ['sessions', sessionId, 'widgets'] as const,
  widget: (id: Id) => ['widgets', id] as const,
  operator: (id: string) => ['operators', id] as const,
  run: (id: Id) => ['runs', id] as const,
  dashboard: (id: Id) => ['dashboards', id] as const,
}

export const projectsQuery = () => queryOptions({ queryKey: keys.projects(), queryFn: listProjects })

export const projectQuery = (id: Id) => queryOptions({ queryKey: keys.project(id), queryFn: () => getProject(id) })

export const sourcesQuery = (projectId: Id) =>
  queryOptions({ queryKey: keys.sources(projectId), queryFn: () => listSources(projectId) })

export const sessionsQuery = (projectId: Id) =>
  queryOptions({ queryKey: keys.sessions(projectId), queryFn: () => listSessions(projectId) })

export const sessionQuery = (id: Id) => queryOptions({ queryKey: keys.session(id), queryFn: () => getSession(id) })

export const entriesQuery = (sessionId: Id) =>
  queryOptions({ queryKey: keys.entries(sessionId), queryFn: () => listEntries(sessionId) })

export const sessionWidgetsQuery = (sessionId: Id) =>
  queryOptions({ queryKey: keys.sessionWidgets(sessionId), queryFn: () => listSessionWidgets(sessionId) })

export const projectWidgetsQuery = (projectId: Id) =>
  queryOptions({ queryKey: keys.projectWidgets(projectId), queryFn: () => listProjectWidgets(projectId) })

export const widgetQuery = (id: Id) => queryOptions({ queryKey: keys.widget(id), queryFn: () => getWidget(id) })

export const operatorQuery = (id: string) =>
  queryOptions({
    queryKey: keys.operator(id),
    queryFn: () => getOperator(id),
    // Operators are immutable: the same id is always the same definition.
    staleTime: Infinity,
  })
