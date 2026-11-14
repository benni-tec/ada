import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { ArrowUp, Info, Square } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'

import { IconButton } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Textarea } from '@/components/ui/textarea'
import { isActive, withLiveParts } from '@/lib/agent-turns'
import {
  agentKeys,
  cancelTurn,
  keys,
  modelsQuery,
  postMessage,
  type AgentTurn,
  type Id,
  type LlmModels,
} from '@/lib/api'

import type { ChatDraft } from './chat-draft'
import { DraftChips } from './context-chips'
import { ModelPicker } from './model-picker'

/** Whether an agent will answer: only when `session_agent` names a model that can run. */
function agentOf(models: LlmModels | undefined): 'yes' | 'no' | 'unknown' {
  if (!models) return 'unknown'
  const agent = models.models.find((model) => model.id === models.session_agent)
  return agent?.available ? 'yes' : 'no'
}

/**
 * Where messages are written. Enter sends, Shift+Enter starts a new line. The message
 * carries the draft's chips as its context and the picked model. While the agent answers,
 * a stop button asks it to stop. Without an agent the message is still recorded in the
 * session, and the composer says plainly that nobody will answer, and how to change that.
 */
export function Composer({
  sessionId,
  draft,
  activeTurn,
  tools,
}: {
  sessionId: Id
  draft: ChatDraft
  /** The agent's latest turn, while it is queued or running. */
  activeTurn: AgentTurn | undefined
  /** Controls at the left of the toolbar, e.g. "Add widget". */
  tools?: ReactNode
}) {
  const queryClient = useQueryClient()
  const { projectId } = useParams({ strict: false })
  const inputId = useId()
  const noteId = useId()
  const input = useRef<HTMLTextAreaElement>(null)
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  // A message was recorded and the server said nobody will answer it.
  const [unanswered, setUnanswered] = useState(false)
  const models = useQuery(modelsQuery())
  const model = picked ?? models.data?.session_agent ?? null
  const agent = unanswered ? 'no' : agentOf(models.data)

  // A chip added from elsewhere on the page: the person says next what they want.
  useEffect(() => {
    if (draft.focusRequest > 0) input.current?.focus()
  }, [draft.focusRequest])

  const send = useMutation({
    mutationFn: (message: string) =>
      postMessage(sessionId, {
        text: message,
        context: draft.chips.flatMap((chip) => chip.context),
        ...(model ? { model } : {}),
      }),
    onSuccess: async ({ turn }) => {
      setText('')
      draft.clearChips()
      setUnanswered(turn === null)
      // The turn as queued, so the record shows it before its first event arrives.
      if (turn) queryClient.setQueryData(agentKeys.turn(turn.id), withLiveParts(turn))
      await queryClient.invalidateQueries({ queryKey: keys.entries(sessionId) })
    },
  })

  const stop = useMutation({
    mutationFn: (turnId: Id) => cancelTurn(turnId),
    onSuccess: (_, turnId) => queryClient.invalidateQueries({ queryKey: agentKeys.turn(turnId) }),
  })

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (text.trim() !== '' && !send.isPending) send.mutate(text.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2" aria-label="Write a message">
      {agent === 'no' && (
        <p id={noteId} role="note" className="flex items-start gap-2 rounded-md border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          <Info aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          <span>
            No agent is configured, so nobody will answer here: your messages are recorded in the session, and an agent
            connected over MCP can read them. To have the platform’s agent answer, add a provider with its key and pick
            the session agent in{' '}
            {projectId ? (
              <Link to="/projects/$projectId/settings" params={{ projectId }} className="underline underline-offset-2">
                Settings
              </Link>
            ) : (
              'Settings'
            )}
            .
          </span>
        </p>
      )}
      <div className="flex flex-col gap-2 rounded-xl border bg-background p-2 shadow-xs focus-within:ring-3 focus-within:ring-ring/50">
        <DraftChips chips={draft.chips} onRemove={draft.removeChip} />
        <label htmlFor={inputId} className="sr-only">
          Message
        </label>
        <Textarea
          ref={input}
          id={inputId}
          value={text}
          rows={2}
          aria-describedby={agent === 'no' ? noteId : undefined}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter is a new line; Enter that ends a composition (an
            // IME choosing characters) is not a send.
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={agent === 'no' ? 'Add a note or a question to the session' : 'Ask the agent, or say what to show'}
          className="max-h-48 min-h-10 resize-none border-0 bg-transparent px-1 shadow-none focus-visible:ring-0 dark:bg-transparent"
        />
        <div className="flex items-center gap-1">
          {tools}
          {models.data && model && agent === 'yes' && (
            <ModelPicker models={models.data} value={model} onChange={setPicked} />
          )}
          <span className="flex-1" />
          {activeTurn && isActive(activeTurn) && (
            <IconButton
              label="Stop the agent"
              variant="outline"
              size="icon-sm"
              disabled={stop.isPending}
              onClick={() => stop.mutate(activeTurn.id)}
            >
              <Square className="fill-current" />
            </IconButton>
          )}
          <IconButton label="Send" type="submit" variant="default" size="icon-sm" disabled={send.isPending || text.trim() === ''}>
            <ArrowUp />
          </IconButton>
        </div>
      </div>
      {send.error && <ErrorNotice error={send.error} prefix="Not sent:" />}
      {stop.error && <ErrorNotice error={stop.error} prefix="Not stopped:" />}
    </form>
  )
}
