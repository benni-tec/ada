import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ChatDraftContext, useChatDraftState } from '@/components/chat/chat-draft'
import { SessionChat } from '@/components/chat/session-chat'
import { DashboardPanel } from '@/components/dashboards/dashboard-panel'
import { EditableTitle } from '@/components/editable-title'
import { ConflictNotice, ErrorNotice, Loading } from '@/components/notices'
import { PageType } from '@/components/page-header'
import { getSession, keys, renameSession, sessionQuery, setPanelDashboard, type Session } from '@/lib/api'
import { useRevisedUpdate } from '@/lib/revisions'

type Search = {
  /** A widget to scroll to and highlight; the MCP tools link to it this way. */
  widget?: string
}

export const Route = createFileRoute('/projects/$projectId/sessions/$sessionId')({
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.widget === 'string' && search.widget !== '' ? { widget: search.widget } : {},
  component: SessionPage,
})

/**
 * A session: its conversation with the agent and the record of what was made, and when
 * the session has one, its dashboard beside it, half and half.
 */
function SessionPage() {
  const { projectId, sessionId } = Route.useParams()
  const { widget: highlighted } = Route.useSearch()
  const session = useQuery(sessionQuery(sessionId))
  // The page holds the draft, so the dashboard half's "Add widget" can put its chip on it.
  const draft = useChatDraftState()
  const rename = useRevisedUpdate({
    queryKey: keys.session(sessionId),
    read: () => getSession(sessionId),
    update: renameSession,
    describeConflict: (latest) =>
      `Someone else changed this session while you were editing: its title is now “${latest.title}”. ` +
      'Your title was not saved; save again to replace it.',
    alsoInvalidate: [keys.sessions(projectId)],
  })
  const detach = useRevisedUpdate({
    queryKey: keys.session(sessionId),
    read: () => getSession(sessionId),
    update: (current: Session) => setPanelDashboard(current, null),
    describeConflict: () =>
      'Someone else changed this session meanwhile, so the dashboard was not detached. It has been read again; try again.',
  })

  if (session.isPending)
    return (
      <div className="p-6">
        <Loading what="the session" />
      </div>
    )
  if (session.error)
    return (
      <div className="p-6">
        <ErrorNotice error={session.error} prefix="The session cannot be loaded:" />
      </div>
    )

  const panel = session.data.panel_dashboard_id
  return (
    <ChatDraftContext value={draft}>
      <div className="flex h-full min-h-0 flex-col lg:flex-row">
        <section aria-label="Conversation" className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="mx-auto flex w-full max-w-4xl shrink-0 flex-col gap-1 px-4 pt-4">
            <PageType type="session" />
            <EditableTitle value={session.data.title} label="session title" {...rename} />
            {detach.conflict && <ConflictNotice message={detach.conflict} onDismiss={detach.reset} />}
            {detach.error && <ErrorNotice error={new Error(detach.error)} prefix="Not detached:" />}
          </header>
          <SessionChat projectId={projectId} sessionId={sessionId} highlightedWidget={highlighted} />
        </section>
        {panel && (
          <DashboardPanel
            dashboardId={panel}
            onDetach={() => void detach.save(null).catch(() => {})}
            detaching={detach.pending}
          />
        )}
      </div>
    </ChatDraftContext>
  )
}
