// What a session shows beside its conversation, as tabs: the REST calls, the models and the
// queries (docs/contracts.md, "Session attachments"). index.ts re-exports it.

import { queryOptions } from '@tanstack/react-query'

import { alertKeys, getAlertRule } from './alerts'
import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

/** One tab beside a session. `ref` names the thing by its kind: a dashboard, report
 * *version*, alert rule, source, widget or session id, a pipeline's operator id, or a web
 * page's address. `title` is the thing's name when it was attached. */
export type Attachment = Schemas['Attachment']
export type AttachmentKind = Schemas['AttachmentKind']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  // A 204 has no body.
  if (!response.ok || (data === undefined && response.status !== 204)) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data as T
}

/** Oldest first. */
export const listAttachments = (sessionId: Id) =>
  unwrap(api.GET('/api/sessions/{session_id}/attachments', { params: { path: { session_id: sessionId } } }))

/**
 * Shows something beside the session; attaching it again returns the same attachment. A
 * report may be named by its id, which attaches its latest version (the answer's `ref`).
 */
export const attach = (sessionId: Id, kind: AttachmentKind, ref: string, title?: string) =>
  unwrap(
    api.POST('/api/sessions/{session_id}/attachments', {
      params: { path: { session_id: sessionId } },
      body: title === undefined ? { kind, ref } : { kind, ref, title },
    }),
  )

export const detach = (sessionId: Id, attachmentId: Id) =>
  unwrap(
    api.DELETE('/api/sessions/{session_id}/attachments/{attachment_id}', {
      params: { path: { session_id: sessionId, attachment_id: attachmentId } },
    }),
  )

/** A report version on its own: what a report tab shows, frozen at the version's run. */
export const getReportVersion = (id: Id) =>
  unwrap(api.GET('/api/report-versions/{version_id}', { params: { path: { version_id: id } } }))

export const attachmentKeys = {
  // Under ['sessions', id], with the session's entries and widgets (./queries.ts).
  list: (sessionId: Id) => ['sessions', sessionId, 'attachments'] as const,
  reportVersion: (id: Id) => ['report-versions', id] as const,
}

export const attachmentsQuery = (sessionId: Id) =>
  queryOptions({ queryKey: attachmentKeys.list(sessionId), queryFn: () => listAttachments(sessionId) })

/** Under ['alert-rules'], so a live alert event refetches it with every other alert view. */
export const alertRuleQuery = (id: Id) => queryOptions({ queryKey: alertKeys.rule(id), queryFn: () => getAlertRule(id) })

export const reportVersionQuery = (id: Id) =>
  queryOptions({
    queryKey: attachmentKeys.reportVersion(id),
    queryFn: () => getReportVersion(id),
    // A version never changes.
    staleTime: Infinity,
  })
