import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useBlocker, useNavigate } from '@tanstack/react-router'
import { Check, FileText, MessagesSquare, Move, Sparkles, X } from 'lucide-react'
import { useId, useMemo, useState, type ReactNode } from 'react'

import { AlertBadges } from '@/components/alerts/alert-badges'
import { AddWidget } from '@/components/chat/add-widget'
import { ChatDraftContext, pipelineChip, useChatDraftState } from '@/components/chat/chat-draft'
import { AgentPanel } from '@/components/dashboards/agent-panel'
import { DashboardGrid } from '@/components/dashboards/dashboard-grid'
import { describeRange } from '@/components/dashboards/ranges'
import { TimeRangeControl } from '@/components/dashboards/time-range-control'
import { useDashboardRun, useDashboardWrite } from '@/components/dashboards/use-dashboard'
import { VersionHistory } from '@/components/dashboards/version-history'
import { IconButton } from '@/components/icon-action'
import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import {
  dashboardQuery,
  dashboardVersionsQuery,
  editDashboard,
  keys,
  projectWidgetsQuery,
  setDefaultTimeRange,
  startSessionFromDashboard,
  type DashboardSlot,
  type DashboardTimeRange,
  type DashboardVersion,
  type Pipeline,
} from '@/lib/api'

type Search = {
  /** Look at this version number instead of the current one. */
  version?: number
}

export const Route = createFileRoute('/projects/$projectId/dashboards/$dashboardId')({
  validateSearch: (search: Record<string, unknown>): Search => {
    const version = Number(search.version)
    return Number.isInteger(version) && version > 0 ? { version } : {}
  },
  component: DashboardPage,
})

function Section({ title, children }: { title: string; children: ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  )
}

const panelKey = 'ada-dashboard-agent-panel'

/** Whether the agent panel is open, remembered in this browser. Closed at first: opening
 * it finds or creates the dashboard's agent session, which a mere look should not do. */
function usePanelOpen() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(panelKey) === 'open'
    } catch {
      return false
    }
  })
  const set = (next: boolean) => {
    setOpen(next)
    try {
      localStorage.setItem(panelKey, next ? 'open' : 'closed')
    } catch {
      // Not remembered, but applied.
    }
  }
  return [open, set] as const
}

function DashboardPage() {
  const { projectId, dashboardId } = Route.useParams()
  const { version: viewing } = Route.useSearch()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const view = useQuery(dashboardQuery(dashboardId))
  const versions = useQuery(dashboardVersionsQuery(dashboardId))
  const widgets = useQuery(projectWidgetsQuery(projectId))
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  const writes = useDashboardWrite(dashboardId)
  const draft = useChatDraftState()
  const [panelOpen, setPanelOpen] = usePanelOpen()
  const [editing, setEditing] = useState(false)
  // The layout being edited: moves and resizes change only this, Done saves it as one
  // version. Null while nothing has changed.
  const [layout, setLayout] = useState<DashboardSlot[] | null>(null)
  // Unsaved changes: leaving in the app asks first, and so does closing or reloading the tab.
  useBlocker({
    shouldBlockFn: () => !window.confirm('The layout has unsaved changes. Leave without saving them?'),
    disabled: layout === null,
    enableBeforeUnload: layout !== null,
  })

  // The range this viewer picked; until then, the dashboard's own.
  const [picked, setPicked] = useState<DashboardTimeRange | null>(null)
  const dashboard = view.data?.dashboard
  const range = picked ?? dashboard?.default_time_range ?? {}
  // One run for the range: every widget below reads it.
  const run = useDashboardRun(dashboardId, range, dashboard !== undefined)

  const startSession = useMutation({
    mutationFn: () => startSessionFromDashboard(projectId, dashboardId, `Questions about ${dashboard?.name ?? 'a dashboard'}`),
    onSuccess: async (session) => {
      await queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
      await navigate({ to: '/projects/$projectId/sessions/$sessionId', params: { projectId, sessionId: session.id } })
    },
  })

  if (view.isPending)
    return (
      <div className="p-6">
        <Loading what="the dashboard" />
      </div>
    )
  if (view.error)
    return (
      <div className="p-6">
        <ErrorNotice error={view.error} prefix="The dashboard cannot be loaded:" />
      </div>
    )

  const { dashboard: record, version: current } = view.data
  const old = viewing !== undefined ? versions.data?.find((version) => version.number === viewing) : undefined
  const shown = old ?? current
  const sameAsDefault = describeRange(range) === describeRange(record.default_time_range)
  const restore = (version: DashboardVersion) =>
    void writes
      .write((latest) => editDashboard(latest, [...version.slots]))
      .then(async (saved) => {
        if (saved) await navigate({ to: '.', search: {} })
      })
  // Done: the edited layout becomes one new version, on the revision last shown. A
  // conflict keeps the changes and stays in editing, so Done can be pressed again.
  const finishEditing = async () => {
    if (layout !== null && !(await writes.write((latest) => editDashboard(latest, layout)))) return
    setLayout(null)
    setEditing(false)
  }
  const discardLayout = () => {
    setLayout(null)
    setEditing(false)
  }
  // "Add widget" puts the pipeline, this dashboard and the slot on the agent's message.
  const addWidget = (slot?: string) => (pipeline: Pipeline) => {
    draft.addChip(pipelineChip(pipeline, { id: dashboardId, name: record.name, slot }))
    setPanelOpen(true)
  }

  return (
    <ChatDraftContext value={draft}>
      <div className="flex h-full min-h-0">
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="flex flex-col gap-6 p-4 md:p-6">
            <PageHeader
              type="dashboard"
              title={record.name}
              below={
                <>
                  <p className="text-sm text-muted-foreground">
                    Showing {describeRange(range)}
                    {sameAsDefault ? ' (the dashboard’s default)' : ''} · version {shown?.number ?? 'none yet'}
                    {layout !== null && !old && ' · unsaved layout changes'}
                  </p>
                  <AlertBadges dashboardId={dashboardId} />
                </>
              }
              actions={
                <>
                  <AddWidget projectId={projectId} variant="default" onPick={addWidget()} />
                  {!old && (shown?.slots.length ?? 0) > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-pressed={editing}
                      disabled={writes.pending}
                      onClick={() => (editing ? void finishEditing() : setEditing(true))}
                    >
                      {editing ? <Check data-icon="inline-start" aria-hidden="true" /> : <Move data-icon="inline-start" aria-hidden="true" />}
                      {!editing ? 'Edit layout' : writes.pending ? 'Saving…' : 'Done'}
                    </Button>
                  )}
                  {editing && layout !== null && (
                    <IconButton label="Discard the layout changes" variant="outline" onClick={discardLayout}>
                      <X />
                    </IconButton>
                  )}
                  <Button asChild variant="outline" size="sm">
                    <Link to="/projects/$projectId/reports/new" params={{ projectId }} search={{ dashboard: dashboardId }}>
                      <FileText data-icon="inline-start" aria-hidden="true" />
                      Generate report
                    </Link>
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => startSession.mutate()} disabled={startSession.isPending}>
                    <MessagesSquare data-icon="inline-start" aria-hidden="true" />
                    {startSession.isPending ? 'Starting…' : 'Start a session from this dashboard'}
                  </Button>
                  {!panelOpen && (
                    <IconButton label="Open the agent panel" variant="outline" onClick={() => setPanelOpen(true)}>
                      <Sparkles />
                    </IconButton>
                  )}
                </>
              }
            />
            {startSession.error && <ErrorNotice error={startSession.error} prefix="No session started:" />}

            <TimeRangeControl
              // A new default, or a range picked elsewhere, resets the fields.
              key={describeRange(range)}
              range={range}
              isDefault={sameAsDefault}
              onShow={setPicked}
              onSaveDefault={(next) =>
                void writes.write((latest) => setDefaultTimeRange(latest, next)).then((saved) => saved && setPicked(null))
              }
              saving={writes.pending}
            />
            {writes.conflict && <ConflictNotice message={writes.conflict} onDismiss={writes.dismissConflict} />}
            {writes.error && <ErrorNotice error={new Error(writes.error)} prefix="Not saved:" />}

            {old && (
              <p
                role="status"
                className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
              >
                You are looking at version {old.number}, not the current one.{' '}
                <Link
                  to="/projects/$projectId/dashboards/$dashboardId"
                  params={{ projectId, dashboardId }}
                  className="underline underline-offset-2"
                >
                  Back to the current version
                </Link>
              </p>
            )}
            {viewing !== undefined && !old && versions.isSuccess && (
              <ErrorNotice error={new Error(`Version ${viewing} does not exist.`)} />
            )}
            {run.error ? (
              <ErrorNotice error={run.error} prefix="The data cannot be read:" />
            ) : widgets.error ? (
              <ErrorNotice error={widgets.error} prefix="The widgets cannot be loaded:" />
            ) : run.isPending || widgets.isPending ? (
              <Loading what="the widgets" />
            ) : (
              <DashboardGrid
                slots={(!old && layout) || shown?.slots || []}
                widgets={widgetsById}
                run={{ id: run.data.id, frozen: false, what: 'The dashboard’s current run' }}
                editing={editing && !old}
                onChange={old ? undefined : setLayout}
                empty={old ? undefined : (slot) => <AddWidget projectId={projectId} onPick={addWidget(slot.name)} />}
              />
            )}

            <Section title="Version history">
              {versions.isPending ? (
                <Loading what="the versions" />
              ) : versions.error ? (
                <ErrorNotice error={versions.error} prefix="The versions cannot be loaded:" />
              ) : (
                <VersionHistory
                  dashboard={record}
                  versions={versions.data}
                  viewing={old?.number}
                  onRestore={restore}
                  restoring={writes.pending}
                />
              )}
            </Section>
          </div>
        </div>
        {panelOpen && <AgentPanel dashboard={record} onClose={() => setPanelOpen(false)} />}
      </div>
    </ChatDraftContext>
  )
}
