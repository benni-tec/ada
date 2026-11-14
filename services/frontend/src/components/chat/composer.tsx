import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { ArrowUp, ChartLine, Info, Microscope, Square } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'

import { IconButton } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Vahti } from '@/components/vahti/vahti'
import { isActive, withLiveParts } from '@/lib/agent-turns'
import { withSettings } from '@/lib/settings-sections'
import {
  agentKeys,
  cancelTurn,
  delegateAnalysis,
  delegateResearch,
  keys,
  modelsQuery,
  postMessage,
  sessionQuery,
  type AgentTurn,
  type Id,
  type LlmModels,
} from '@/lib/api'

import type { ChatDraft } from './chat-draft'
import { DraftChips } from './context-chips'
import { ModelPicker } from './model-picker'

/** Whether an agent will answer: only when the model a message goes to can run. */
function agentOf(models: LlmModels | undefined, model: string | null | undefined): 'yes' | 'no' | 'unknown' {
  if (!models) return 'unknown'
  return usable(models, model) ? 'yes' : 'no'
}

function usable(models: LlmModels | undefined, id: string | null | undefined): boolean {
  return models?.models.some((model) => model.id === id && model.available) ?? false
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
  const [focused, setFocused] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  // A message was recorded and the server said nobody will answer it.
  const [unanswered, setUnanswered] = useState(false)
  const models = useQuery(modelsQuery())
  const session = useQuery(sessionQuery(sessionId))
  // Research falls back to the session agent's model, as the backend does.
  const researcher = models.data?.research_agent ?? models.data?.session_agent
  // Who answers a message that names no model: in a research session, the researcher.
  const isResearch = session.data?.agent === 'research'
  const answering = isResearch ? researcher : models.data?.session_agent
  // A research model that cannot run gives way to the session agent's, named in the message.
  const fallback = usable(models.data, answering) ? answering : (models.data?.session_agent ?? answering)
  const model = picked ?? fallback ?? null
  const agent = unanswered ? 'no' : agentOf(models.data, model)

  // A chip added from elsewhere on the page: the person says next what they want.
  useEffect(() => {
    if (draft.focusRequest > 0) input.current?.focus()
  }, [draft.focusRequest])

  const send = useMutation({
    mutationFn: (message: string) =>
      postMessage(sessionId, {
        text: message,
        context: draft.chips.flatMap((chip) => chip.context),
        // A research session names no model when the researcher answers: the backend uses it.
        ...(isResearch && model === answering ? {} : model ? { model } : {}),
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

  // The draft as a question for the analyst, with the pipelines its chips name.
  const analysis = useMutation({
    mutationFn: (brief: string) =>
      delegateAnalysis(
        sessionId,
        brief.split('\n')[0].slice(0, 80),
        brief,
        draft.chips.flatMap((chip) => chip.context).flatMap((item) => (item.kind === 'pipeline' ? [item.operator_id] : [])),
      ),
    onSuccess: async () => {
      setText('')
      draft.clearChips()
      await queryClient.invalidateQueries({ queryKey: keys.entries(sessionId) })
      if (projectId) await queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
    },
  })

  // The draft as a brief for the research agent, which works in a session of its own.
  const research = useMutation({
    mutationFn: (brief: string) => delegateResearch(sessionId, brief.split('\n')[0].slice(0, 80), brief),
    onSuccess: async () => {
      setText('')
      await queryClient.invalidateQueries({ queryKey: keys.entries(sessionId) })
      if (projectId) await queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
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
              <Link to="." search={withSettings('models')} resetScroll={false} className="underline underline-offset-2">
                Settings
              </Link>
            ) : (
              'Settings'
            )}
            .
          </span>
        </p>
      )}
      {/* Vahti peeks over the box while someone writes, and ducks while the agent answers. */}
      <div className="relative">
        <span
          aria-hidden="true"
          data-up={focused && text.trim() !== '' && !isActive(activeTurn)}
          className="vahti-perch pointer-events-none absolute right-6 bottom-full z-0"
        >
          <Vahti pose="peek" size={34} label="" filter={false} look={[-3, 5]} />
        </span>
        <div
          className="relative z-10 flex flex-col gap-2 rounded-xl border bg-background p-2 shadow-xs focus-within:ring-3 focus-within:ring-ring/50"
          onFocus={() => setFocused(true)}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false)
          }}
        >
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
            {models.data && model && models.data.models.some((option) => option.available) && (
              <ModelPicker models={models.data} value={model} defaultId={answering} onChange={setPicked} />
            )}
            <span className="flex-1" />
            {models.data && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={research.isPending || text.trim() === '' || !researcher}
                title={researcher ? undefined : 'Pick a session or research agent in Settings first'}
                onClick={() => research.mutate(text.trim())}
              >
                <Microscope aria-hidden="true" />
                Research
              </Button>
            )}
            {models.data && session.data?.agent === 'session' && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={analysis.isPending || text.trim() === '' || !models.data.session_agent}
                title={
                  models.data.session_agent
                    ? 'Hand the question to the analyst, with the pipelines added as chips'
                    : 'Pick a session agent in Settings first'
                }
                onClick={() => analysis.mutate(text.trim())}
              >
                <ChartLine aria-hidden="true" />
                Analyse
              </Button>
            )}
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
      </div>
      {send.error && <ErrorNotice error={send.error} prefix="Not sent:" />}
      {research.error && <ErrorNotice error={research.error} prefix="Not delegated:" />}
      {analysis.error && <ErrorNotice error={analysis.error} prefix="Not delegated:" />}
      {stop.error && <ErrorNotice error={stop.error} prefix="Not stopped:" />}
    </form>
  )
}
