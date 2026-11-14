import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useId, useMemo, useState, type ReactNode } from 'react'

import { AlertBadges } from '@/components/alerts/alert-badges'
import { DashboardGrid } from '@/components/dashboards/dashboard-grid'
import { describeRange } from '@/components/dashboards/ranges'
import { TimeRangeControl } from '@/components/dashboards/time-range-control'
import { useDashboardRun, useDashboardWrite } from '@/components/dashboards/use-dashboard'
import { VersionHistory } from '@/components/dashboards/version-history'
import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import {
  dashboardQuery,
  dashboardVersionsQuery,
  editDashboard,
  keys,
  projectWidgetsQuery,
  setDefaultTimeRange,
  startSessionFromDashboard,
  type DashboardTimeRange,
  type DashboardVersion,
} from '@/lib/api'
import { DashboardCrumb } from '@/components/breadcrumbs'

type Search = {
  /** Look at this version number instead of the current one. */
  version?: number
}

export const Route = createFileRoute('/projects/$projectId/dashboards/$dashboardId')({
  staticData: { crumb: DashboardCrumb },
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

  if (view.isPending) return <Loading what="the dashboard" />
  if (view.error) return <ErrorNotice error={view.error} prefix="The dashboard cannot be loaded:" />

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

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">{record.name}</h1>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Showing {describeRange(range)}
            {sameAsDefault ? ' (the dashboard’s default)' : ''} · version {shown?.number ?? 'none yet'}
          </p>
          <AlertBadges dashboardId={dashboardId} />
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <div className="flex flex-wrap gap-2">
            <Link
              to="/projects/$projectId/reports/new"
              params={{ projectId }}
              search={{ dashboard: dashboardId }}
              className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium dark:border-neutral-700"
            >
              Generate report
            </Link>
          <button
            type="button"
            onClick={() => startSession.mutate()}
            disabled={startSession.isPending}
            className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium disabled:opacity-50 dark:border-neutral-700"
          >
            {startSession.isPending ? 'Starting…' : 'Start a session from this dashboard'}
          </button>
          </div>
          {startSession.error && <ErrorNotice error={startSession.error} prefix="No session started:" />}
        </div>
      </header>

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
        <p role="status" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
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
          slots={shown?.slots ?? []}
          widgets={widgetsById}
          run={{ id: run.data.id, frozen: false, what: 'The dashboard’s current run' }}
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
  )
}
