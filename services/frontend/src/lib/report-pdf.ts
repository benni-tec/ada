// What a report's PDF says that is not drawing: its link back into ADA and its citations.

import type { Report, ReportVersion } from '@/lib/api'

/** A report version's page in ADA on `origin`. */
export const reportUrl = (origin: string, report: Pick<Report, 'id' | 'project_id'>, version: Pick<ReportVersion, 'version'>) =>
  `${origin}/projects/${report.project_id}/reports/${report.id}?version=${encodeURIComponent(version.version)}`

/** Source numbers as a citation, runs joined: [1–3], [7]. */
export function citation(numbers: number[]): string {
  const runs: [number, number][] = []
  for (const n of numbers) {
    const last = runs.at(-1)
    if (last && n === last[1] + 1) last[1] = n
    else runs.push([n, n])
  }
  return runs.map(([from, to]) => (from === to ? `[${from}]` : `[${from}–${to}]`)).join(', ')
}
