import { useQuery } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { SessionRecord } from '@/components/session-record'
import { cn } from '@/lib/utils'
import { entriesQuery, sessionWidgetsQuery, turnQuery, type Id } from '@/lib/api'
import { useProjectRun } from '@/lib/view-run'

import { AddWidget } from './add-widget'
import { ChatDraftContext, pipelineChip, useChatDraft, useChatDraftState } from './chat-draft'
import { Composer } from './composer'

/**
 * A session as a chat: its record scrolling above, the composer at the bottom. Used by the
 * session page and by a dashboard's agent panel. The record follows new entries and the
 * agent's streaming answer while one is at the bottom; scrolled up to read, it stays put.
 */
export function SessionChat({
  projectId,
  sessionId,
  highlightedWidget,
  dashboard,
  className,
}: {
  projectId: Id
  sessionId: Id
  /** A widget to scroll to and mark (`?widget=`). */
  highlightedWidget?: string
  /** On a dashboard's panel: "Add widget" is then for that dashboard (a new slot). */
  dashboard?: { id: Id; name: string }
  className?: string
}) {
  const pageDraft = useChatDraft()
  const ownDraft = useChatDraftState()
  const draft = pageDraft ?? ownDraft
  const entries = useQuery(entriesQuery(sessionId))
  const widgets = useQuery(sessionWidgetsQuery(sessionId))
  const widgetsById = useMemo(() => new Map((widgets.data ?? []).map((widget) => [widget.id, widget])), [widgets.data])
  // One run for the whole record, as a dashboard has: every card shows the same cut, and
  // a new run follows changed data.
  const run = useProjectRun(projectId)

  // The agent's latest turn: while it runs, the composer offers to stop it.
  const lastTurnId = entries.data?.findLast((entry) => entry.kind === 'agent_turn')?.ref ?? null
  const lastTurn = useQuery({ ...turnQuery(lastTurnId ?? ''), enabled: lastTurnId !== null })

  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  useFollowBottom(scroller, content, highlightedWidget === undefined)
  useScrollToWidget(highlightedWidget, entries.isSuccess)

  return (
    <ChatDraftContext value={draft}>
      <div className={cn('flex h-full min-h-0 flex-col', className)}>
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto" data-chat-scroll>
          <div ref={content} className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4">
            {entries.isPending ? (
              <Loading what="the session record" />
            ) : entries.error ? (
              <ErrorNotice error={entries.error} prefix="The session record cannot be loaded:" />
            ) : (
              <>
                {run.error && <ErrorNotice error={run.error} prefix="The data cannot be read:" />}
                <SessionRecord
                  projectId={projectId}
                  entries={entries.data}
                  widgets={widgetsById}
                  run={{ id: run.data?.id ?? null, frozen: false, what: 'The session’s current run' }}
                  highlightedWidget={highlightedWidget}
                />
              </>
            )}
          </div>
        </div>
        <div className="shrink-0 border-t bg-background p-3">
          <div className="mx-auto w-full max-w-4xl">
            <Composer
              sessionId={sessionId}
              draft={draft}
              activeTurn={lastTurn.data}
              tools={
                <AddWidget
                  projectId={projectId}
                  variant="ghost"
                  onPick={(pipeline) =>
                    draft.addChip(pipelineChip(pipeline, dashboard && { id: dashboard.id, name: dashboard.name }))
                  }
                />
              }
            />
          </div>
        </div>
      </div>
    </ChatDraftContext>
  )
}

/**
 * Keeps the record scrolled to the bottom while the person is there: on opening, as
 * entries arrive and as the agent's answer grows. Scrolled up, it leaves them be.
 */
function useFollowBottom(
  scroller: React.RefObject<HTMLDivElement | null>,
  content: React.RefObject<HTMLDivElement | null>,
  startAtBottom: boolean,
) {
  const atBottom = useRef(startAtBottom)
  useLayoutEffect(() => {
    const element = scroller.current
    if (!element) return
    const onScroll = () => {
      atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => element.removeEventListener('scroll', onScroll)
  }, [scroller])
  useEffect(() => {
    const element = scroller.current
    const inner = content.current
    if (!element || !inner) return
    const follow = () => {
      if (atBottom.current) element.scrollTo({ top: element.scrollHeight })
    }
    follow()
    const observer = new ResizeObserver(follow)
    observer.observe(inner)
    return () => observer.disconnect()
  }, [scroller, content])
}

/** Brings the widget named in the address into view once the record is there. */
function useScrollToWidget(widgetId: string | undefined, ready: boolean) {
  useEffect(() => {
    if (!widgetId || !ready) return
    document.getElementById(`widget-${widgetId}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }, [widgetId, ready])
}
