import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

/** The REST API, typed from the backend's OpenAPI schema (`moon run frontend:generate`). */
export const api = createClient<paths>({
  // Absolute, because the client builds Request objects, which reject relative URLs
  // outside a browser (in tests).
  baseUrl: window.location.origin,
  // Looked up per call, so tests can stub the global.
  fetch: (request) => globalThis.fetch(request),
})

export type Schemas = components['schemas']

/** The body of every error response. A 409 also carries both revisions. */
export type ApiError = {
  detail: string
  expected_revision?: number
  revision?: number
}

/** Thrown by the helpers below, so TanStack Query treats a failed call as an error. */
export class ApiFailure extends Error {
  readonly status: number
  readonly body: ApiError | undefined

  constructor(status: number, body: ApiError | undefined) {
    super(body?.detail ?? `Request failed: ${status}`)
    this.status = status
    this.body = body
  }

  /** Someone else changed the record since it was read; read again and retry. */
  get isConflict() {
    return this.status === 409
  }
}
