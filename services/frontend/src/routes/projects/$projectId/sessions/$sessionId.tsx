import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { AttachmentPanel } from '@/components/attachments/attachment-panel'
import { ChatDraftContext, useChatDraftState } from '@/components/chat/chat-draft'
import { SessionChat } from '@/components/chat/session-chat'
import { EditableTitle } from '@/components/editable-title'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageType } from '@/components/page-header'
import { getSession, keys, renameSession, sessionQuery } from '@/lib/api'
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
 * A session: its conversation with the agent and the record of what was made, and beside
 * it, half and half, what is attached to it as tabs (a dashboard, a report, a web page…).
 */
function SessionPage() {
  const { projectId, sessionId } = Route.useParams()
  const { widget: highlighted } = Route.useSearch()
  const session = useQuery(sessionQuery(sessionId))
  // The page holds the draft, so a dashboard tab's "Add widget" can put its chip on it.
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

  return (
    <ChatDraftContext value={draft}>
      <div className="flex h-full min-h-0 flex-col lg:flex-row">
        <section aria-label="Conversation" className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="mx-auto flex w-full max-w-4xl shrink-0 flex-col gap-1 px-4 pt-4">
            <PageType type="session" />
            <EditableTitle value={session.data.title} label="session title" {...rename} />
          </header>
          <SessionChat projectId={projectId} sessionId={sessionId} highlightedWidget={highlighted} />
        </section>
        {/* Keyed: the open tab and what was seen of the list belong to one session. */}
        <AttachmentPanel key={sessionId} projectId={projectId} sessionId={sessionId} />
      </div>
    </ChatDraftContext>
  )
}
