import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CircleAlert, CircleCheck, Code, LoaderCircle, Microscope } from 'lucide-react'

import { operatorQuery, sessionTurnsQuery, widgetQuery, type Id, type SessionEntry, type Widget } from '@/lib/api'
import { delegationState, type DelegationState } from '@/lib/research'
import type { CardRun } from '@/lib/view-run'

import { AgentTurnEntry } from './chat/agent-turn'
import { RecordedContext } from './chat/context-chips'
import { Markdown } from './chat/markdown'
import { ErrorNotice } from './notices'
import { Provenance, Time } from './provenance'
import { Bubble, BubbleContent } from './ui/bubble'
import { Message, MessageContent, MessageHeader } from './ui/message'
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
          ) : entry.kind === 'delegation' ? (
            <DelegationEntry entry={entry} projectId={projectId} />
          ) : entry.kind === 'report' ? (
            <ReportEntry entry={entry} projectId={projectId} />
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

const delegationStates: Record<DelegationState, { label: string; icon: typeof CircleCheck; className: string }> = {
  running: { label: 'Running', icon: LoaderCircle, className: 'animate-spin' },
  done: { label: 'Done', icon: CircleCheck, className: 'text-emerald-700 dark:text-emerald-400' },
  failed: { label: 'Failed', icon: CircleAlert, className: 'text-destructive' },
}

/** Work handed to a research agent: a card to its session, with how it is going. */
function DelegationEntry({ entry, projectId }: { entry: SessionEntry; projectId: Id }) {
  const { data: turns, isError } = useQuery({ ...sessionTurnsQuery(entry.ref ?? ''), enabled: !!entry.ref })
  const state = turns ? delegationStates[delegationState(turns)] : null
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-card px-4 py-3 text-sm">
      <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Microscope aria-hidden="true" className="size-3.5" />
        Handed to the research agent
      </p>
      <div className="flex items-center justify-between gap-3">
        {entry.ref ? (
          <Link
            to="/projects/$projectId/sessions/$sessionId"
            params={{ projectId, sessionId: entry.ref }}
            className="min-w-0 truncate font-medium underline-offset-2 hover:underline"
          >
            {entry.text}
          </Link>
        ) : (
          <span className="font-medium">{entry.text}</span>
        )}
        {isError && <span className="shrink-0 text-xs text-muted-foreground">Status unavailable</span>}
        {state && (
          <span className="flex shrink-0 items-center gap-1 text-xs">
            <state.icon aria-hidden="true" className={`size-3.5 ${state.className}`} />
            {state.label}
          </span>
        )}
      </div>
      <Provenance actor={entry.actor} at={entry.created_at} />
    </div>
  )
}

/** What the research agent found, as a message from it, with the way to its session. */
function ReportEntry({ entry, projectId }: { entry: SessionEntry; projectId: Id }) {
  return (
    <Message>
      <MessageContent className="gap-1.5">
        <MessageHeader className="gap-2 px-0">
          <Microscope aria-hidden="true" className="size-3.5" />
          <span>Research agent ({entry.actor.name})</span>
          <span className="font-normal">
            <Time value={entry.created_at} />
          </span>
        </MessageHeader>
        <Bubble variant="outline">
          <BubbleContent>
            <Markdown>{entry.text ?? ''}</Markdown>
          </BubbleContent>
        </Bubble>
        {entry.ref && (
          <Link
            to="/projects/$projectId/sessions/$sessionId"
            params={{ projectId, sessionId: entry.ref }}
            className="text-xs text-muted-foreground underline underline-offset-2"
          >
            Open the research session
          </Link>
        )}
      </MessageContent>
    </Message>
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
