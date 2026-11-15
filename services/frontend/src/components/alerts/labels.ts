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

/** The views, most severe first; equal severities keep their order. */
export function mostSevereFirst<T extends AlertView>(views: readonly T[]): T[] {
  return [...views].sort((a, b) => severities.indexOf(a.rule.severity) - severities.indexOf(b.rule.severity))
}

/** The most severe of the active alerts, or null when none is active. */
export function worstActive(views: readonly AlertView[]): Severity | null {
  return countBySeverity(views)[0]?.[0] ?? null
}

/** Pills (count badges) by severity: red only for critical, amber for warnings. */
export const severityPillClasses: Record<Severity, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  warning: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  info: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200',
}

/** Text of an active alert or count by severity, matching the pills. */
export const severityTextClasses: Record<Severity, string> = {
  critical: 'font-medium text-red-700 dark:text-red-400',
  warning: 'font-medium text-amber-700 dark:text-amber-400',
  info: 'font-medium text-sky-700 dark:text-sky-400',
}

/** "2 critical, 1 warning" */
export function countsText(counts: readonly [Severity, number][]): string {
  return counts.map(([severity, count]) => `${count} ${severityLabels[severity].toLowerCase()}`).join(', ')
}
