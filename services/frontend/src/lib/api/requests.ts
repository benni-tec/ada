// The REST calls of docs/contracts.md. TEMPORARY in the same way as ./models: once the
// routes are in the OpenAPI schema, integration can move these onto the typed `api`
// client; the function names and signatures stay.

import { ApiFailure, type ApiError } from './client'
import type { DataSource, Id, Operator, Project, Session, SessionEntry, Widget } from './models'

async function request<T>(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  // Absolute, like the typed client, so the same call works in tests outside a browser.
  const response = await globalThis.fetch(new URL(path, window.location.origin), {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const error = (await response.json().catch(() => undefined)) as ApiError | undefined
    throw new ApiFailure(response.status, typeof error?.detail === 'string' ? error : undefined)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

const segment = encodeURIComponent

// Projects

export const listProjects = () => request<Project[]>('GET', '/api/projects')

export const getProject = (id: Id) => request<Project>('GET', `/api/projects/${segment(id)}`)

export const createProject = (name: string) => request<Project>('POST', '/api/projects', { name })

export const renameProject = (project: Project, name: string) =>
  request<Project>('PATCH', `/api/projects/${segment(project.id)}`, { name, expected_revision: project.revision })

// Sources

export const listSources = (projectId: Id) =>
  request<DataSource[]>('GET', `/api/projects/${segment(projectId)}/sources`)

// Sessions

export const listSessions = (projectId: Id) =>
  request<Session[]>('GET', `/api/projects/${segment(projectId)}/sessions`)

export const createSession = (projectId: Id, title: string) =>
  request<Session>('POST', `/api/projects/${segment(projectId)}/sessions`, { title })

export const getSession = (id: Id) => request<Session>('GET', `/api/sessions/${segment(id)}`)

export const renameSession = (session: Session, title: string) =>
  request<Session>('PATCH', `/api/sessions/${segment(session.id)}`, {
    title,
    expected_revision: session.revision,
  })

export const listEntries = (sessionId: Id) =>
  request<SessionEntry[]>('GET', `/api/sessions/${segment(sessionId)}/entries`)

export const addMessage = (sessionId: Id, text: string) =>
  request<SessionEntry>('POST', `/api/sessions/${segment(sessionId)}/messages`, { text })

export const listSessionWidgets = (sessionId: Id) =>
  request<Widget[]>('GET', `/api/sessions/${segment(sessionId)}/widgets`)

// Widgets and operators

export const getWidget = (id: Id) => request<Widget>('GET', `/api/widgets/${segment(id)}`)

export const getOperator = (id: string) => request<Operator>('GET', `/api/operators/${segment(id)}`)
