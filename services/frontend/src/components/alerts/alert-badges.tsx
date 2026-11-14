import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { dashboardAlertsQuery, type Id } from '@/lib/api'

import { countBySeverity, countsText } from './labels'
import { SeverityBadge } from './severity'

/**
 * The firing alerts of a dashboard's rules, counted by severity, linking to the project's
 * alert feed. Shows nothing while loading or when the dashboard has no rules; a quiet line
 * when nothing fires.
 */
export function AlertBadges({ dashboardId }: { dashboardId: Id }) {
  const { data } = useQuery(dashboardAlertsQuery(dashboardId))
  if (!data) return null
  const counts = countBySeverity(data)
  if (counts.length === 0) {
    return (
      <p role="status" className="text-xs text-neutral-500">
        No alerts firing
      </p>
    )
  }
  const total = counts.reduce((sum, [, count]) => sum + count, 0)
  return (
    <Link
      to="/projects/$projectId/alerts"
      params={{ projectId: data[0].alert.project_id }}
      aria-label={`${total} firing ${total === 1 ? 'alert' : 'alerts'}: ${countsText(counts)}. Open the alert feed`}
      className="inline-flex flex-wrap items-center gap-1 rounded-md hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      {counts.map(([severity, count]) => (
        <SeverityBadge key={severity} severity={severity} count={count} />
      ))}
    </Link>
  )
}
