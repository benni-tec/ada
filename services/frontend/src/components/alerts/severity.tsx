import type { Severity } from '@/lib/api'

import { severityLabels, severityPillClasses } from './labels'

/** The severity as a word on a coloured pill; the word carries the meaning, not the colour. */
export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${severityPillClasses[severity]}`}
    >
      {count !== undefined && <span className="tabular-nums">{count}</span>}
      {severityLabels[severity]}
    </span>
  )
}
