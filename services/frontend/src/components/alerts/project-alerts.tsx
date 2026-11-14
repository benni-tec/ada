import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { alertFeedQuery, type Id } from '@/lib/api'

import { countBySeverity } from './labels'
import { SeverityBadge } from './severity'

/** The project page's alerts section: what fires now, by severity, and the way to the feed. */
export function ProjectAlerts({ projectId }: { projectId: Id }) {
  const { data, error, isPending } = useQuery(alertFeedQuery(projectId, 'firing'))
  const headingId = useId()
  const counts = data ? countBySeverity(data) : []
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-lg font-semibold">
        Alerts
      </h2>
      {isPending ? (
        <Loading what="alerts" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The alerts cannot be loaded:" />
      ) : counts.length === 0 ? (
        <p className="text-sm text-neutral-500">Nothing is firing.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {counts.map(([severity, count]) => (
            <SeverityBadge key={severity} severity={severity} count={count} />
          ))}
          <span className="text-neutral-600 dark:text-neutral-400">firing</span>
        </div>
      )}
      <Link
        to="/projects/$projectId/alerts"
        params={{ projectId }}
        className="text-sm font-medium underline underline-offset-2"
      >
        Alert feed and rules
      </Link>
    </section>
  )
}
