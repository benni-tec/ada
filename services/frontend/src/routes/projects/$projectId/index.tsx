import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { CircleAlert } from 'lucide-react'
import { useId, type ReactNode } from 'react'

import { describeRange } from '@/components/dashboards/ranges'
import { EditableTitle } from '@/components/editable-title'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Time } from '@/components/provenance'
import {
  alertFeedQuery,
  dashboardsQuery,
  getProject,
  keys,
  projectQuery,
  renameProject,
  reportsQuery,
  sessionsQuery,
  sourcesQuery,
  type Id,
} from '@/lib/api'
import { pageTypes, type PageTypeName } from '@/lib/page-types'
import { accessLabels, describeFreshness } from '@/lib/sources'
import { useRevisedUpdate } from '@/lib/revisions'
import { withSettings } from '@/lib/settings-sections'

export const Route = createFileRoute('/projects/$projectId/')({
  component: ProjectPage,
})

/**
 * The project at a glance: how much of each it holds, what happened lately, and the state
 * of its data sources. Everything is listed in the sidebar; this page does not repeat it.
 */
function ProjectPage() {
  const { projectId } = Route.useParams()
  const { data: project, error, isPending } = useQuery(projectQuery(projectId))
  const rename = useRevisedUpdate({
    queryKey: keys.project(projectId),
    read: () => getProject(projectId),
    update: renameProject,
    describeConflict: (latest) =>
      `Someone else renamed this project while you were editing: it is now “${latest.name}”. ` +
      'Your name was not saved; save again to replace it.',
    alsoInvalidate: [keys.projects()],
  })

  if (isPending)
    return (
      <div className="p-6">
        <Loading what="the project" />
      </div>
    )
  if (error)
    return (
      <div className="p-6">
        <ErrorNotice error={error} prefix="The project cannot be loaded:" />
      </div>
    )

  return (
    <div className="flex flex-col gap-8 p-4 md:p-6">
      <PageHeader type="project" title={<EditableTitle value={project.name} label="project name" {...rename} />} />
      <Counts projectId={projectId} />
      <div className="grid gap-8 xl:grid-cols-2">
        <RecentSessions projectId={projectId} />
        <Sources projectId={projectId} />
      </div>
    </div>
  )
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id={headingId} className="text-lg font-semibold">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  )
}

/** One number per kind, with the kind's icon; alerts lead to the feed. */
function Counts({ projectId }: { projectId: Id }) {
  const sessions = useQuery(sessionsQuery(projectId))
  const dashboards = useQuery(dashboardsQuery(projectId))
  const reports = useQuery(reportsQuery(projectId))
  const firing = useQuery(alertFeedQuery(projectId, 'firing'))
  const sources = useQuery(sourcesQuery(projectId))
  const count = (data: unknown[] | undefined) => (data ? String(data.length) : '…')
  return (
    <ul aria-label="In this project" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      <Count type="session" label="Sessions" value={count(sessions.data)} />
      <Count type="dashboard" label="Dashboards" value={count(dashboards.data)} />
      <Count type="report" label="Reports" value={count(reports.data)} />
      <Count
        type="alerts"
        label="Active alerts"
        value={count(firing.data)}
        link={
          <Link to="/projects/$projectId/alerts" params={{ projectId }} className="text-xs underline underline-offset-2">
            Feed and rules
          </Link>
        }
      />
      <Count type="source" label="Data sources" value={count(sources.data)} />
    </ul>
  )
}

function Count({ type, label, value, link }: { type: PageTypeName; label: string; value: string; link?: ReactNode }) {
  const Icon = pageTypes[type].icon
  return (
    <li className="flex flex-col gap-1 rounded-lg border bg-card p-4">
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon aria-hidden="true" className="size-3.5" />
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {link}
    </li>
  )
}

const listClass = 'divide-y rounded-lg border'

function RecentSessions({ projectId }: { projectId: Id }) {
  const { data, error, isPending } = useQuery(sessionsQuery(projectId))
  const { data: dashboards } = useQuery(dashboardsQuery(projectId))
  const recent = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5)
  const names = new Map((dashboards ?? []).map((dashboard) => [dashboard.id, dashboard]))
  return (
    <Section title="Recent sessions">
      {isPending ? (
        <Loading what="sessions" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The sessions cannot be loaded:" />
      ) : recent.length === 0 ? (
        <p className="text-sm text-muted-foreground">No sessions yet. Start one with the + beside “Sessions”.</p>
      ) : (
        <ul className={listClass}>
          {recent.map((session) => {
            const beside = session.panel_dashboard_id ? names.get(session.panel_dashboard_id) : undefined
            return (
              <li key={session.id}>
                <Link
                  to="/projects/$projectId/sessions/$sessionId"
                  params={{ projectId, sessionId: session.id }}
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/50 focus-visible:bg-muted/50"
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate font-medium">{session.title}</span>
                    {beside && (
                      <span className="truncate text-xs text-muted-foreground">
                        With {beside.name} ({describeRange(beside.default_time_range)})
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    <Time value={session.created_at} />
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Section>
  )
}

/** Each source with where it reads from and how fresh it is, read only: they are added
 * and edited in Settings. */
function Sources({ projectId }: { projectId: Id }) {
  const { data: sources, error, isPending } = useQuery(sourcesQuery(projectId))
  return (
    <Section
      title="Data sources"
      action={
        <Link to="." search={withSettings('data-sources')} resetScroll={false} className="text-sm underline underline-offset-2">
          Manage in Settings
        </Link>
      }
    >
      {isPending ? (
        <Loading what="data sources" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The data sources cannot be loaded:" />
      ) : sources.length === 0 ? (
        <p className="text-sm text-muted-foreground">No data sources yet. Add one in Settings, or have an agent register one over MCP.</p>
      ) : (
        <ul className={listClass}>
          {sources.map((source) => (
            <li key={source.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{source.name}</span>
                <span className="text-xs text-muted-foreground">
                  {accessLabels[source.access_kind]} · {source.format.toUpperCase()}
                </span>
              </div>
              <p className="truncate font-mono text-xs text-muted-foreground" title={source.address}>
                {source.address}
              </p>
              <p className="text-xs text-muted-foreground">
                Refresh: {describeFreshness(source.freshness)}
                {source.last_checked_at && (
                  <>
                    {' · '}checked <Time value={source.last_checked_at} />
                  </>
                )}
              </p>
              {source.last_error && (
                <p className="flex items-start gap-1 text-xs text-amber-800 dark:text-amber-300">
                  <CircleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
                  Last refresh failed: {source.last_error}. Widgets on it show stale data.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
