import { useQuery } from '@tanstack/react-query'
import { Code } from 'lucide-react'

import { operatorQuery, widgetQuery, type Id, type SessionEntry, type Widget } from '@/lib/api'
import type { CardRun } from '@/lib/view-run'

import { AgentTurnEntry } from './chat/agent-turn'
import { RecordedContext } from './chat/context-chips'
import { ErrorNotice } from './notices'
import { Provenance } from './provenance'
import { Bubble, BubbleContent } from './ui/bubble'
import { Message, MessageContent } from './ui/message'
import { WidgetCard } from './widget-card'

/**
 * A session's record in order, as a conversation: the person's messages, the platform
 * agent's answers with the steps it took, and the operators and widgets that were made
 * (by that agent, or by an external one whose own conversation happens in its client and
 * only its tool calls land here).
 */
export function SessionRecord({
  projectId,
  entries,
  widgets,
  run,
  highlightedWidget,
}: {
  projectId: Id
  entries: SessionEntry[]
  widgets: Map<Id, Widget>
  /** The session's run: every widget card reads it. */
  run: CardRun
  highlightedWidget?: string
}) {
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Nothing here yet. Write a message below, or let an agent work in this session over MCP.
      </p>
    )
  }
  return (
    <ol aria-label="Session record" className="flex flex-col gap-5">
      {entries.map((entry) => (
        <li key={entry.id}>
          {entry.kind === 'message' ? (
            <MessageEntry entry={entry} projectId={projectId} />
          ) : entry.kind === 'agent_turn' ? (
            entry.ref ? (
              <AgentTurnEntry turnId={entry.ref} />
            ) : null
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

/** A message: the person's on the right, anyone else's (an external agent's) on the left. */
function MessageEntry({ entry, projectId }: { entry: SessionEntry; projectId: Id }) {
  const own = entry.actor.kind === 'user'
  const align = own ? 'end' : 'start'
  return (
    <Message align={align}>
      <MessageContent className="gap-1.5">
        <div className={own ? 'self-end' : undefined}>
          <Provenance actor={entry.actor} at={entry.created_at} />
        </div>
        <Bubble align={align} variant={own ? 'secondary' : 'outline'}>
          <BubbleContent className="whitespace-pre-wrap">{entry.text}</BubbleContent>
        </Bubble>
        {entry.context && entry.context.length > 0 && <RecordedContext context={entry.context} projectId={projectId} />}
      </MessageContent>
    </Message>
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
    <div className={`flex flex-col gap-1 border-l-2 py-1 pl-4 ${external ? 'border-violet-400 dark:border-violet-700' : 'border-border'}`}>
      <p className="text-sm font-medium">
        {operator ? (operatorKinds[operator.kind] ?? `Added a ${operator.kind} operator`) : 'Added an operator'}
        {operator && (
          <span className="ml-2 font-normal text-muted-foreground">
            {operator.output.columns.length} column{operator.output.columns.length === 1 ? '' : 's'}
          </span>
        )}
      </p>
      <Provenance actor={entry.actor} at={entry.created_at} note={entry.text} />
      {sql && (
        <details className="text-xs">
          <summary className="flex cursor-pointer items-center gap-1 text-muted-foreground">
            <Code aria-hidden="true" className="size-3.5" />
            SQL
          </summary>
          <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">{sql}</pre>
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
  if (!widget) return <div className="h-40 animate-pulse rounded-lg bg-muted" />
  return <WidgetCard widget={widget} run={run} highlighted={highlighted} />
}
