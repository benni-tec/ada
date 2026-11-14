import { severities, type AlertView, type Severity } from '@/lib/api'

export const severityLabels: Record<Severity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
}

/** A key as text: `region: north, start: 2024-01-01`. */
export function keyText(key: Record<string, unknown>): string {
  const parts = Object.entries(key).map(([column, value]) => `${column}: ${String(value)}`)
  return parts.length > 0 ? parts.join(', ') : 'all rows'
}

/** How often a rule is checked, in words. */
export function intervalText(seconds: number | null | undefined): string {
  if (!seconds) return 'when its data changes'
  if (seconds % 86400 === 0) return seconds === 86400 ? 'every day' : `every ${seconds / 86400} days`
  if (seconds % 3600 === 0) return seconds === 3600 ? 'every hour' : `every ${seconds / 3600} hours`
  if (seconds % 60 === 0) return seconds === 60 ? 'every minute' : `every ${seconds / 60} minutes`
  return `every ${seconds} seconds`
}

/** Firing alerts per severity, most severe first, leaving out severities with none. */
export function countBySeverity(views: readonly AlertView[]): [Severity, number][] {
  const counts = new Map<Severity, number>()
  for (const { alert, rule } of views) {
    if (alert.state === 'firing') counts.set(rule.severity, (counts.get(rule.severity) ?? 0) + 1)
  }
  return severities.filter((severity) => counts.has(severity)).map((severity) => [severity, counts.get(severity) ?? 0])
}

/** "2 critical, 1 warning" */
export function countsText(counts: readonly [Severity, number][]): string {
  return counts.map(([severity, count]) => `${count} ${severityLabels[severity].toLowerCase()}`).join(', ')
}
