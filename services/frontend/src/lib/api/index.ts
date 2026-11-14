import { api, ApiFailure, type Schemas } from './client'

export { api, ApiFailure } from './client'
export type { ApiError, Schemas } from './client'
export type * from './models'
export * from './dashboards'
export * from './queries'
export * from './requests'
export * from './reports'
export * from './runs'
export * from './alerts'
export * from './attachments'
export * from './agent'
export * from './settings'
export * from './judges'
export * from './statistical-models'

export type Health = Schemas['Health']

export const healthParts = [
  { key: 'api', label: 'API' },
  { key: 'database', label: 'Database' },
  { key: 'queue', label: 'Queue' },
  { key: 'worker', label: 'Worker' },
  { key: 'analysis_store', label: 'Analysis store' },
] as const satisfies readonly { key: Exclude<keyof Health, 'status'>; label: string }[]

export async function fetchHealth(): Promise<Health> {
  const { data, error, response } = await api.GET('/api/health')
  if (data) return data
  // A degraded service answers 503 with the same body.
  if (response.status === 503) return error as unknown as Health
  throw new ApiFailure(response.status, undefined)
}

/** What to tell a person about a failed call: the server's `detail` when it sent one. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiFailure) return error.body?.detail ?? `The request failed (${error.status}).`
  if (error instanceof TypeError) return 'The API cannot be reached.'
  return error instanceof Error ? error.message : String(error)
}
