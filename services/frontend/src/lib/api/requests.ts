// The REST calls of docs/contracts.md, on the typed client: paths, parameters, bodies and
// answers are checked against the backend's OpenAPI schema.

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { DataSource, Id, Project, Session } from './models'

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

export type NewSource = Schemas['NewSource']
/** What can change in a source; its access kind and format stay. */
export type SourceChange = Omit<Schemas['SourceChange'], 'expected_revision'>

export const registerSource = (projectId: Id, source: NewSource) =>
  unwrap(api.POST('/api/projects/{project_id}/sources', { params: { path: { project_id: projectId } }, body: source }))

export const updateSource = (source: DataSource, change: SourceChange) =>
  unwrap(
    api.PATCH('/api/sources/{source_id}', {
      params: { path: { source_id: source.id } },
      body: { ...change, expected_revision: source.revision },
    }),
  )

/** Queues a refresh now, whatever the freshness policy says; the outcome comes as an event. */
export const refreshSource = (id: Id) =>
  unwrap(api.POST('/api/sources/{source_id}/refresh', { params: { path: { source_id: id } }, body: { force: true } }))

/** Has Context.dev watch the source's page; the source then refreshes when the page changes. */
export const watchSource = (id: Id) =>
  unwrap(api.POST('/api/sources/{source_id}/watch', { params: { path: { source_id: id } } }))

export const unwatchSource = (id: Id) =>
  unwrap(api.DELETE('/api/sources/{source_id}/watch', { params: { path: { source_id: id } } }))

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

/** What the session shows beside its conversation, oldest first. */
export const listAttachments = (sessionId: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}/attachments', { params: { path: { session_id: sessionId } } }))

/** Takes an attachment away from beside the session; the thing itself stays. */
export async function detachFromSession(sessionId: Id, attachmentId: Id): Promise<void> {
  const { error, response } = await api.DELETE('/api/sessions/{session_id}/attachments/{attachment_id}', {
    params: { path: { session_id: sessionId, attachment_id: attachmentId } },
  })
  // A 204 has no body, so there is no data to unwrap.
  if (!response.ok) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
}

export const listEntries = (sessionId: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}/entries', { params: { path: { session_id: sessionId } } }))

/** Hands a brief to a research agent in a new child session, which reports back here. */
export const delegateResearch = (sessionId: Id, title: string, brief: string) =>
  unwrap(
    api.POST('/api/sessions/{session_id}/research', {
      params: { path: { session_id: sessionId } },
      body: { title, brief },
    }),
  )

// Messages are posted with their context and model by `postMessage` (agent.ts).

export const listSessionWidgets = (sessionId: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}/widgets', { params: { path: { session_id: sessionId } } }))

// Widgets and operators

export const listProjectWidgets = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/widgets', { params: { path: { project_id: projectId } } }))

export const getWidget = (id: Id) =>
  unwrap(api.GET('/api/widgets/{widget_id}', { params: { path: { widget_id: id } } }))

export const getOperator = (id: string) =>
  unwrap(api.GET('/api/operators/{operator_id}', { params: { path: { operator_id: id } } }))
