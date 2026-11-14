// The REST calls of docs/contracts.md, on the typed client: paths, parameters, bodies and
// answers are checked against the backend's OpenAPI schema.

import { api, ApiFailure, type ApiError } from './client'
import type { Id, Project, Session, SessionEntry } from './models'

type Answer<T> = { data?: T; error?: unknown; response: Response }

/** The data of a successful call; an ApiFailure, with the server's detail, otherwise. */
async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

// Projects

export const listProjects = () => unwrap(api.GET('/api/projects'))

export const getProject = (id: Id) =>
  unwrap(api.GET('/api/projects/{project_id}', { params: { path: { project_id: id } } }))

export const createProject = (name: string) => unwrap(api.POST('/api/projects', { body: { name } }))

export const renameProject = (project: Project, name: string) =>
  unwrap(
    api.PATCH('/api/projects/{project_id}', {
      params: { path: { project_id: project.id } },
      body: { name, expected_revision: project.revision },
    }),
  )

// Sources

export const listSources = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/sources', { params: { path: { project_id: projectId } } }))

// Sessions

export const listSessions = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/sessions', { params: { path: { project_id: projectId } } }))

export const createSession = (projectId: Id, title: string) =>
  unwrap(
    api.POST('/api/projects/{project_id}/sessions', {
      params: { path: { project_id: projectId } },
      body: { title },
    }),
  )

export const getSession = (id: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}', { params: { path: { session_id: id } } }))

export const renameSession = (session: Session, title: string) =>
  unwrap(
    api.PATCH('/api/sessions/{session_id}', {
      params: { path: { session_id: session.id } },
      body: { title, expected_revision: session.revision },
    }),
  )

/** Puts a dashboard beside the session, or with null takes it away. */
export const setPanelDashboard = (session: Session, dashboardId: Id | null) =>
  unwrap(
    api.PATCH('/api/sessions/{session_id}', {
      params: { path: { session_id: session.id } },
      body: { panel_dashboard_id: dashboardId, expected_revision: session.revision },
    }),
  )

// Typed as the wave 3 entry (models.ts), which the generated schema does not have yet.
export const listEntries = (sessionId: Id): Promise<SessionEntry[]> =>
  unwrap(api.GET('/api/sessions/{session_id}/entries', { params: { path: { session_id: sessionId } } }))

// Messages are posted with their context and model by `postMessage` (agent.ts, wave 3).

export const listSessionWidgets = (sessionId: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}/widgets', { params: { path: { session_id: sessionId } } }))

// Widgets and operators

export const listProjectWidgets = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/widgets', { params: { path: { project_id: projectId } } }))

export const getWidget = (id: Id) =>
  unwrap(api.GET('/api/widgets/{widget_id}', { params: { path: { widget_id: id } } }))

export const getOperator = (id: string) =>
  unwrap(api.GET('/api/operators/{operator_id}', { params: { path: { operator_id: id } } }))
