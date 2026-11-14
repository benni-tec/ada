import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { LayoutDashboard, X } from 'lucide-react'
import { useMemo } from 'react'

import { AddWidget } from '@/components/chat/add-widget'
import { pipelineChip, useChatDraft } from '@/components/chat/chat-draft'
import { IconButton } from '@/components/icon-action'
import { ErrorNotice, Loading } from '@/components/notices'
import { dashboardQuery, projectWidgetsQuery, type Id } from '@/lib/api'

import { DashboardGrid } from './dashboard-grid'
import { describeRange } from './ranges'
import { useDashboardRun } from './use-dashboard'

/**
 * The dashboard beside a session's conversation, half the screen: a black bar saying
 * "Dashboard" and its name, with an × that detaches it from the session, and the
 * dashboard's grid below at its own default range on one run, like the dashboard page.
 * The page's live stream refetches it on `dashboard.changed`, so a widget the agent pins
 * appears here. An empty slot's "Add widget" goes to the session's conversation.
 */
export function DashboardPanel({
  dashboardId,
  onDetach,
  detaching = false,
}: {
  dashboardId: Id
  onDetach: () => void
  detaching?: boolean
}) {
  const draft = useChatDraft()
  const view = useQuery(dashboardQuery(dashboardId))
  const projectId = view.data?.dashboard.project_id
  const widgets = useQuery({ ...projectWidgetsQuery(projectId ?? ''), enabled: projectId !== undefined })
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  const range = view.data?.dashboard.default_time_range ?? {}
  const run = useDashboardRun(dashboardId, range, view.isSuccess)
  const name = view.data?.dashboard.name

  return (
    <aside aria-label="Dashboard" className="flex min-h-0 min-w-0 flex-1 flex-col border-t lg:border-t-0 lg:border-l">
      {/* Black in both themes: it marks where the dashboard begins, apart from the chat. */}
      <header className="flex h-11 shrink-0 items-center gap-2 bg-black px-3 text-white">
        <LayoutDashboard aria-hidden="true" className="size-4 shrink-0" />
        <span className="text-xs font-medium tracking-wide text-white/70 uppercase">Dashboard</span>
        <h2 className="min-w-0 truncate text-sm font-semibold">
          {view.data ? (
            <Link
              to="/projects/$projectId/dashboards/$dashboardId"
              params={{ projectId: view.data.dashboard.project_id, dashboardId }}
              className="rounded-sm hover:underline focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none"
            >
              {name}
            </Link>
          ) : (
            '…'
          )}
        </h2>
        <span className="flex-1" />
        <IconButton
          label="Detach the dashboard"
          onClick={onDetach}
          disabled={detaching}
          className="text-white hover:bg-white/15 hover:text-white focus-visible:ring-white/60 dark:hover:bg-white/15"
        >
          <X />
        </IconButton>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {view.isPending ? (
          <Loading what="the dashboard" />
        ) : view.error ? (
          <ErrorNotice error={view.error} prefix="The dashboard cannot be loaded:" />
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              {describeRange(range)} · version {view.data.version?.number ?? 'none yet'}
            </p>
            {run.error ? (
              <ErrorNotice error={run.error} prefix="The data cannot be read:" />
            ) : widgets.error ? (
              <ErrorNotice error={widgets.error} prefix="The widgets cannot be loaded:" />
            ) : run.isPending || widgets.isPending ? (
              <Loading what="the widgets" />
            ) : (
              <DashboardGrid
                slots={view.data.version?.slots ?? []}
                widgets={widgetsById}
                run={{ id: run.data.id, frozen: false, what: 'The dashboard’s current run' }}
                empty={
                  draft && projectId
                    ? (slot) => (
                        <AddWidget
                          projectId={projectId}
                          onPick={(pipeline) =>
                            draft.addChip(pipelineChip(pipeline, { id: dashboardId, name: name ?? 'the dashboard', slot: slot.name }))
                          }
                        />
                      )
                    : undefined
                }
              />
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
