import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'

import {
  addMessage,
  keys,
  operatorQuery,
  widgetQuery,
  type Id,
  type SessionEntry,
  type Widget,
} from '@/lib/api'
import type { CardRun } from '@/lib/view-run'

import { ErrorNotice } from './notices'
import { Provenance } from './provenance'
import { WidgetCard } from './widget-card'

/**
 * A session's record in order: messages, operators added and widgets shown. It is not a
 * chat transcript; an external agent's conversation happens in its own client, and only
 * its tool calls land here.
 */
export function SessionRecord({
  entries,
  widgets,
  run,
  highlightedWidget,
}: {
  entries: SessionEntry[]
  widgets: Map<Id, Widget>
  /** The session's run: every widget card reads it. */
  run: CardRun
  highlightedWidget?: string
}) {
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-neutral-300 p-6 text-center text-sm text-neutral-500 dark:border-neutral-700">
        Nothing here yet. Write a message, or let an agent work in this session over MCP.
      </p>
    )
  }
  return (
    <ol aria-label="Session record" className="flex flex-col gap-4">
      {entries.map((entry) => (
        <li key={entry.id}>
          {entry.kind === 'message' ? (
            <MessageEntry entry={entry} />
          ) : entry.kind === 'operator' ? (
            <OperatorEntry entry={entry} />
          ) : (
            <WidgetEntry
              entry={entry}
              known={entry.ref ? widgets.get(entry.ref) : undefined}
              run={run}
              highlighted={!!entry.ref && entry.ref === highlightedWidget}
            />
          )}
        </li>
      ))}
    </ol>
  )
}

function MessageEntry({ entry }: { entry: SessionEntry }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-neutral-100 px-4 py-3 dark:bg-neutral-900">
      <Provenance actor={entry.actor} at={entry.created_at} />
      <p className="text-sm whitespace-pre-wrap">{entry.text}</p>
    </div>
  )
}

const operatorKinds: Record<string, string> = {
  source: 'Loaded a data source',
  extract: 'Extracted rows from a document',
  input: 'Added an input slot',
  transform: 'Added a transform',
  statistic: 'Computed a statistic',
  agent: 'Added an agent step',
}

function OperatorEntry({ entry }: { entry: SessionEntry }) {
  const { data: operator } = useQuery({ ...operatorQuery(entry.ref ?? ''), enabled: !!entry.ref })
  const sql = operator?.kind === 'transform' && typeof operator.params.sql === 'string' ? operator.params.sql : null
  const external = entry.actor.kind === 'external_agent'
  return (
    <div
      className={`flex flex-col gap-1 border-l-2 py-1 pl-4 ${
        external ? 'border-violet-400 dark:border-violet-700' : 'border-neutral-300 dark:border-neutral-700'
      }`}
    >
      <p className="text-sm font-medium">
        {operator ? (operatorKinds[operator.kind] ?? `Added a ${operator.kind} operator`) : 'Added an operator'}
        {operator && (
          <span className="ml-2 font-normal text-neutral-500">
            {operator.output.columns.length} column{operator.output.columns.length === 1 ? '' : 's'}
          </span>
        )}
      </p>
      <Provenance actor={entry.actor} at={entry.created_at} note={entry.text} />
      {sql && (
        <details className="text-xs">
          <summary className="cursor-pointer text-neutral-600 dark:text-neutral-400">SQL</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-neutral-100 p-2 dark:bg-neutral-900">{sql}</pre>
        </details>
      )}
    </div>
  )
}

function WidgetEntry({
  entry,
  known,
  run,
  highlighted,
}: {
  entry: SessionEntry
  known: Widget | undefined
  run: CardRun
  highlighted: boolean
}) {
  // The session's widget list normally has it; read it alone when the entry arrived first.
  const { data, error } = useQuery({ ...widgetQuery(entry.ref ?? ''), enabled: !!entry.ref && !known })
  const widget = known ?? data
  if (error) return <ErrorNotice error={error} prefix="This widget cannot be shown:" />
  if (!widget) return <div className="h-40 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-900" />
  return <WidgetCard widget={widget} run={run} highlighted={highlighted} />
}

/** Adds a message to the session. Ctrl or Cmd with Enter sends. */
export function MessageForm({ sessionId }: { sessionId: Id }) {
  const queryClient = useQueryClient()
  const inputId = useId()
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: (message: string) => addMessage(sessionId, message),
    onSuccess: () => {
      setText('')
      return queryClient.invalidateQueries({ queryKey: keys.entries(sessionId) })
    },
  })

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (text.trim() !== '' && !send.isPending) send.mutate(text.trim())
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-sm font-medium">
        Message
      </label>
      <textarea
        id={inputId}
        value={text}
        rows={3}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit()
        }}
        placeholder="Add a note or a question to the session"
        className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
      />
      <div className="flex items-center justify-between gap-3">
        {send.error ? <ErrorNotice error={send.error} prefix="Not sent:" /> : <span />}
        <button
          type="submit"
          disabled={send.isPending || text.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {send.isPending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </form>
  )
}
