type Part = 'ok' | 'unavailable'

export type Health = {
  /** Aggregate: ok only if every part is ok. */
  status: 'ok' | 'degraded'
  api: 'ok'
  /** PostgreSQL, which holds the definitions. */
  database: Part
  /** Valkey, the task queue broker. */
  queue: Part
  /** Task worker and scheduler, judged by their heartbeat. */
  worker: Part
  /** DuckDB over the snapshot directory. */
  analysis_store: Part
}

export const healthParts = [
  { key: 'api', label: 'API' },
  { key: 'database', label: 'Database' },
  { key: 'queue', label: 'Queue' },
  { key: 'worker', label: 'Worker' },
  { key: 'analysis_store', label: 'Analysis store' },
] as const satisfies readonly { key: Exclude<keyof Health, 'status'>; label: string }[]

export async function fetchHealth(): Promise<Health> {
  const response = await fetch('/api/health')
  // A degraded service answers 503 with the same body, so read it either way.
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json()
}
