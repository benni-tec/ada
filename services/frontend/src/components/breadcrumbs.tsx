import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'

import { dashboardQuery, reportQuery, sessionQuery, widgetQuery } from '@/lib/api'

/** One step: the kind of page, then its name as the current page. */
function Step({ kind, name }: { kind: string; name?: string }) {
  return (
    <>
      <li aria-hidden="true">/</li>
      <li className={name ? undefined : 'font-medium text-neutral-900 dark:text-neutral-100'}>{kind}</li>
      {name && (
        <>
          <li aria-hidden="true">/</li>
          <li aria-current="page" className="font-medium text-neutral-900 dark:text-neutral-100">
            {name}
          </li>
        </>
      )}
    </>
  )
}

export function SessionCrumb() {
  const { sessionId } = useParams({ strict: false })
  const session = useQuery({ ...sessionQuery(sessionId ?? ''), enabled: Boolean(sessionId) })
  return <Step kind="Session" name={session.data?.title ?? '…'} />
}

export function DashboardCrumb() {
  const { dashboardId } = useParams({ strict: false })
  const dashboard = useQuery({ ...dashboardQuery(dashboardId ?? ''), enabled: Boolean(dashboardId) })
  return <Step kind="Dashboard" name={dashboard.data?.dashboard.name ?? '…'} />
}

export function ReportCrumb() {
  const { reportId } = useParams({ strict: false })
  const report = useQuery({ ...reportQuery(reportId ?? ''), enabled: Boolean(reportId) })
  return <Step kind="Report" name={report.data?.name ?? '…'} />
}

export function NewReportCrumb() {
  return <Step kind="New report" />
}

export function WidgetCrumb() {
  const { widgetId } = useParams({ strict: false })
  const widget = useQuery({ ...widgetQuery(widgetId ?? ''), enabled: Boolean(widgetId) })
  return <Step kind="Widget" name={widget.data ? widget.data.title || 'Untitled widget' : '…'} />
}

export function AlertsCrumb() {
  return <Step kind="Alerts" />
}
