import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useMemo } from 'react'

import { DashboardPanel } from '@/components/dashboards/dashboard-panel'
import { EditableTitle } from '@/components/editable-title'
import { ErrorNotice, Loading } from '@/components/notices'
import { MessageForm, SessionRecord } from '@/components/session-record'
import { entriesQuery, getSession, keys, renameSession, sessionQuery, sessionWidgetsQuery } from '@/lib/api'
import { useRevisedUpdate } from '@/lib/revisions'
import { useProjectRun } from '@/lib/view-run'
import { SessionCrumb } from '@/components/breadcrumbs'

type Search = {
  /** A widget to scroll to and highlight; the MCP tools link to it this way. */
  widget?: string
}

export const Route = createFileRoute('/projects/$projectId/sessions/$sessionId')({
  staticData: { crumb: SessionCrumb },
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.widget === 'string' && search.widget !== '' ? { widget: search.widget } : {},
  component: SessionPage,
})

function SessionPage() {
  const { projectId, sessionId } = Route.useParams()
  const { widget: highlighted } = Route.useSearch()
  const session = useQuery(sessionQuery(sessionId))
  const entries = useQuery(entriesQuery(sessionId))
  const widgets = useQuery(sessionWidgetsQuery(sessionId))
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  const rename = useRevisedUpdate({
    queryKey: keys.session(sessionId),
    read: () => getSession(sessionId),
    update: renameSession,
    describeConflict: (latest) =>
      `Someone else changed this session while you were editing: its title is now “${latest.title}”. ` +
      'Your title was not saved; save again to replace it.',
    alsoInvalidate: [keys.sessions(projectId)],
  })

  // One run for the whole record, as a dashboard has: every card shows the same cut, and
  // a new run follows changed data.
  const run = useProjectRun(projectId)

  useScrollToWidget(highlighted, entries.isSuccess)

  if (session.isPending) return <Loading what="the session" />
  if (session.error) return <ErrorNotice error={session.error} prefix="The session cannot be loaded:" />

  const panel = session.data.panel_dashboard_id
  return (
    <div className={panel ? 'grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]' : 'mx-auto w-full max-w-4xl'}>
      <div className="flex min-w-0 flex-col gap-6">
        <EditableTitle value={session.data.title} label="session title" {...rename} />
        {entries.isPending ? (
          <Loading what="the session record" />
        ) : entries.error ? (
          <ErrorNotice error={entries.error} prefix="The session record cannot be loaded:" />
        ) : (
          <>
            {run.error && <ErrorNotice error={run.error} prefix="The data cannot be read:" />}
            <SessionRecord
              entries={entries.data}
              widgets={widgetsById}
              run={{ id: run.data?.id ?? null, frozen: false, what: 'The session’s current run' }}
              highlightedWidget={highlighted}
            />
          </>
        )}
        <MessageForm sessionId={sessionId} />
      </div>
      {panel && <DashboardPanel dashboardId={panel} />}
    </div>
  )
}

/** Brings the widget named in the address into view once the record is there. */
function useScrollToWidget(widgetId: string | undefined, ready: boolean) {
  useEffect(() => {
    if (!widgetId || !ready) return
    // jsdom has no scrollIntoView.
    document.getElementById(`widget-${widgetId}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }, [widgetId, ready])
}
