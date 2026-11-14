import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { MessagesSquare, PanelRightClose, Sparkles } from 'lucide-react'

import { SessionChat } from '@/components/chat/session-chat'
import { Hint, IconButton } from '@/components/icon-action'
import { ErrorNotice, Loading } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { dashboardSessionQuery, type Dashboard } from '@/lib/api'

/**
 * A chat docked beside the dashboard, secondary to the grid. Its conversation is the
 * dashboard's agent session (found or created when the panel first opens), so every step
 * the agent takes for the dashboard lands in a session like any other.
 */
export function AgentPanel({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const session = useQuery(dashboardSessionQuery(dashboard.id))
  return (
    <aside
      aria-label="Dashboard agent"
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col border-l bg-background shadow-lg sm:w-[26rem] lg:static lg:z-auto lg:w-[26rem] lg:shrink-0 lg:shadow-none xl:w-[30rem]"
    >
      <header className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
        <Sparkles aria-hidden="true" className="size-4" />
        <h2 className="text-sm font-semibold">Agent</h2>
        <span className="flex-1" />
        {session.data && (
          <Hint label="Open as a session">
            <Button asChild variant="ghost" size="icon-sm">
              <Link
                to="/projects/$projectId/sessions/$sessionId"
                params={{ projectId: dashboard.project_id, sessionId: session.data.id }}
                aria-label="Open as a session"
              >
                <MessagesSquare />
              </Link>
            </Button>
          </Hint>
        )}
        <IconButton label="Close the agent panel" onClick={onClose}>
          <PanelRightClose />
        </IconButton>
      </header>
      {session.isPending ? (
        <div className="p-4">
          <Loading what="the dashboard’s agent session" />
        </div>
      ) : session.error ? (
        <div className="p-4">
          <ErrorNotice error={session.error} prefix="The agent session cannot be opened:" />
        </div>
      ) : (
        <SessionChat
          projectId={dashboard.project_id}
          sessionId={session.data.id}
          dashboard={{ id: dashboard.id, name: dashboard.name }}
          className="min-h-0 flex-1"
        />
      )}
    </aside>
  )
}
