import type { DashboardTimeRange } from '@/lib/api'

export const yearOf = (date: string | null | undefined) => (date ? date.slice(0, 4) : '')

/** Whole years: from 1 January of the first to 31 December of the last. A blank end is
 * open: no bound on that side. */
export function yearsToRange(from: string, to: string): DashboardTimeRange {
  return {
    start: from === '' ? null : `${from.padStart(4, '0')}-01-01`,
    end: to === '' ? null : `${to.padStart(4, '0')}-12-31`,
  }
}

export function describeRange(range: DashboardTimeRange): string {
  const [from, to] = [yearOf(range.start), yearOf(range.end)]
  if (from && to) return from === to ? from : `${from} to ${to}`
  if (from) return `${from} onwards`
  if (to) return `up to ${to}`
  return 'all years'
}
