import { api, ApiFailure, type Schemas } from './client'

export { api, ApiFailure } from './client'
export type { ApiError, Schemas } from './client'

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
