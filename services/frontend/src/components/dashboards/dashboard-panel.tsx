import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { OpenLink, ViewBar } from '@/components/attachments/view-bar'
import { AddWidget } from '@/components/chat/add-widget'
import { pipelineChip, useChatDraft } from '@/components/chat/chat-draft'
import { ErrorNotice, Loading } from '@/components/notices'
import { dashboardQuery, projectWidgetsQuery, type Id } from '@/lib/api'

import { DashboardGrid } from './dashboard-grid'
import { describeRange } from './ranges'
import { useDashboardRun } from './use-dashboard'

/**
 * A dashboard in a session's tab: its grid, read only, at its own default range on one
 * run, like the dashboard page, with the way to that page. The page's live stream
 * refetches it on `dashboard.changed`, so a widget the agent pins appears here. An empty
 * slot's "Add widget" goes to the session's conversation, with the dashboard and slot.
 */
export function DashboardPanel({ dashboardId }: { dashboardId: Id }) {
  const draft = useChatDraft()
  const view = useQuery(dashboardQuery(dashboardId))
  const projectId = view.data?.dashboard.project_id
  const widgets = useQuery({ ...projectWidgetsQuery(projectId ?? ''), enabled: projectId !== undefined })
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  const range = view.data?.dashboard.default_time_range ?? {}
  const run = useDashboardRun(dashboardId, range, view.isSuccess)
  const name = view.data?.dashboard.name

  if (view.isPending) return <Loading what="the dashboard" />
  if (view.error) return <ErrorNotice error={view.error} prefix="The dashboard cannot be loaded:" />
  return (
    <div className="flex flex-col gap-3">
      <ViewBar
        open={
          <OpenLink
            label="Open the dashboard"
            to="/projects/$projectId/dashboards/$dashboardId"
            params={{ projectId: view.data.dashboard.project_id, dashboardId }}
          />
        }
      >
        {describeRange(range)} · version {view.data.version?.number ?? 'none yet'}
      </ViewBar>
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
  )
}
