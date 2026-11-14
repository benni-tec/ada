import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { reportsQuery, sessionsQuery, type Id, type Report } from '@/lib/api'

/** The project's reports, newest first, each with the session or dashboard it came from. */
export function ReportsSection({ projectId }: { projectId: Id }) {
  const headingId = useId()
  const { data, error, isPending } = useQuery(reportsQuery(projectId))
  const { data: sessions = [] } = useQuery(sessionsQuery(projectId))
  const sessionTitles = new Map(sessions.map((session) => [session.id, session.title]))
  const reports = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={headingId} className="text-lg font-semibold">
          Reports
        </h2>
        <Link
          to="/projects/$projectId/reports/new"
          params={{ projectId }}
          className="text-sm text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
        >
          Generate from a dashboard
        </Link>
      </div>
      {isPending ? (
        <Loading what="reports" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The reports cannot be loaded:" />
      ) : reports.length === 0 ? (
        <p className="text-sm text-neutral-500">No reports yet. Agents write them in sessions, or generate one from a dashboard.</p>
      ) : (
        <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          {reports.map((report) => (
            <li key={report.id}>
              <Link
                to="/projects/$projectId/reports/$reportId"
                params={{ projectId, reportId: report.id }}
                className="flex flex-col gap-0.5 px-4 py-3 hover:bg-neutral-50 focus-visible:bg-neutral-50 dark:hover:bg-neutral-900 dark:focus-visible:bg-neutral-900"
              >
                <span className="flex items-center justify-between gap-4">
                  <span className="font-medium">{report.name}</span>
                  <span className="text-xs text-neutral-500">
                    <Time value={report.created_at} />
                  </span>
                </span>
                <span className="text-xs text-neutral-500">{origin(report, sessionTitles)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function origin(report: Report, sessionTitles: Map<Id, string>): string {
  if (report.session_id) {
    const title = sessionTitles.get(report.session_id)
    return title ? `From the session “${title}”` : 'From a session'
  }
  return report.dashboard_id ? 'From a dashboard' : ''
}
