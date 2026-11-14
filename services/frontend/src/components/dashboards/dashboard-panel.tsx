import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { dashboardQuery, projectWidgetsQuery, type Id } from '@/lib/api'

import { CompactGrid } from './dashboard-grid'
import { describeRange } from './ranges'
import { useDashboardRun } from './use-dashboard'

/**
 * A compact, live view of a dashboard beside a session's conversation. It follows the
 * dashboard's own default range and reads one run, like the dashboard page; the page's
 * live stream refetches the dashboard on `dashboard.changed`, so an agent that pins a
 * widget here sees it appear.
 */
export function DashboardPanel({ dashboardId }: { dashboardId: Id }) {
  const view = useQuery(dashboardQuery(dashboardId))
  const projectId = view.data?.dashboard.project_id
  const widgets = useQuery({ ...projectWidgetsQuery(projectId ?? ''), enabled: projectId !== undefined })
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  const range = view.data?.dashboard.default_time_range ?? {}
  const run = useDashboardRun(dashboardId, range, view.isSuccess)

  return (
    <aside
      aria-label="Dashboard"
      className="flex min-h-48 min-w-0 flex-col gap-3 rounded-lg border border-neutral-200 p-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto dark:border-neutral-800"
    >
      {view.isPending ? (
        <Loading what="the dashboard" />
      ) : view.error ? (
        <ErrorNotice error={view.error} prefix="The dashboard cannot be loaded:" />
      ) : (
        <>
          <header className="flex flex-col gap-0.5">
            <h2 className="text-sm font-semibold">
              <Link
                to="/projects/$projectId/dashboards/$dashboardId"
                params={{ projectId: view.data.dashboard.project_id, dashboardId }}
                className="hover:underline focus-visible:underline"
              >
                {view.data.dashboard.name}
              </Link>
            </h2>
            <p className="text-xs text-neutral-500">
              {describeRange(range)} · version {view.data.version?.number ?? 'none yet'}
            </p>
          </header>
          {run.error ? (
            <ErrorNotice error={run.error} prefix="The data cannot be read:" />
          ) : widgets.error ? (
            <ErrorNotice error={widgets.error} prefix="The widgets cannot be loaded:" />
          ) : run.isPending || widgets.isPending ? (
            <Loading what="the widgets" />
          ) : (
            <CompactGrid slots={view.data.version?.slots ?? []} widgets={widgetsById} runId={run.data.id} />
          )}
        </>
      )}
    </aside>
  )
}
