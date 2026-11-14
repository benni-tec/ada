import type { Severity } from '@/lib/api'

import { severityLabels } from './labels'

const severityClasses: Record<Severity, string> = {
  critical: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  warning: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  info: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200',
}

/** The severity as a word on a coloured pill; the word carries the meaning, not the colour. */
export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${severityClasses[severity]}`}
    >
      {count !== undefined && <span className="tabular-nums">{count}</span>}
      {severityLabels[severity]}
    </span>
  )
}
