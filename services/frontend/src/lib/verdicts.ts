import { CircleCheck, CircleDashed, OctagonX, TriangleAlert, type LucideIcon } from 'lucide-react'

import type { Verdict } from '@/lib/api'

/** The widget types a judge reviews: text widgets and custom widgets' code. */
export const JUDGED_TYPES = new Set(['text', 'custom'])

const count = (n: number) => `${n} ${n === 1 ? 'finding' : 'findings'}`

/** How a verdict reads at a glance: words and an icon, the colour only adds to them. */
export function verdictSummary(verdict: Verdict | null | undefined): {
  label: string
  Icon: LucideIcon
  className: string
  /** Why it is not reviewed, for a tooltip. */
  reason?: string
} {
  if (!verdict) {
    return {
      label: 'Not reviewed',
      Icon: CircleDashed,
      className: 'text-muted-foreground',
      reason: 'Not reviewed yet: the judge reviews a widget after each change.',
    }
  }
  const findings = verdict.findings.length
  switch (verdict.outcome) {
    case 'unchecked':
      return {
        label: 'Not reviewed',
        Icon: CircleDashed,
        className: 'text-muted-foreground',
        reason: verdict.reason ?? 'The judge did not review it.',
      }
    case 'fail':
      return {
        label: `Failed: ${count(findings)}`,
        Icon: OctagonX,
        className: 'border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200',
      }
    case 'warn':
      return {
        label: count(findings),
        Icon: TriangleAlert,
        className: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100',
      }
    case 'pass':
      return findings === 0
        ? {
            label: 'Reviewed ✓',
            Icon: CircleCheck,
            className: 'text-emerald-800 dark:text-emerald-300',
          }
        : {
            label: count(findings),
            Icon: TriangleAlert,
            className: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100',
          }
  }
}

