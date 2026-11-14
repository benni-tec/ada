import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Brain,
  CircleAlert,
  CircleCheck,
  CircleStop,
  Database,
  LoaderCircle,
  Sparkles,
  Wrench,
} from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Markdown } from '@/components/chat/markdown'
import { ErrorNotice } from '@/components/notices'
import { Time } from '@/components/provenance'
import { Message, MessageContent, MessageHeader } from '@/components/ui/message'
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from '@/components/ui/trace'
import { groupParts, isActive } from '@/lib/agent-turns'
import { turnQuery, type AgentTurn, type Id, type Part, type ReasoningPart, type SourcePart, type ToolPart } from '@/lib/api'

/** An agent turn in the record, read by id; the live stream keeps it current. */
export function AgentTurnEntry({ turnId }: { turnId: Id }) {
  const { data: turn, error, isPending } = useQuery(turnQuery(turnId))
  if (isPending) return <TurnShell model={null}><Waiting title="Loading the agent’s answer" /></TurnShell>
  if (error) return <ErrorNotice error={error} prefix="The agent’s answer cannot be loaded:" />
  return <AgentTurnView turn={turn} />
}

function TurnShell({ model, at, children }: { model: string | null; at?: string; children: ReactNode }) {
  return (
    <Message>
      <MessageContent className="gap-3">
        <MessageHeader className="gap-2 px-0">
          <Sparkles aria-hidden="true" className="size-3.5" />
          <span>Platform agent{model ? ` (${model})` : ''}</span>
          {at && (
            <span className="font-normal">
              <Time value={at} />
            </span>
          )}
        </MessageHeader>
        {children}
      </MessageContent>
    </Message>
  )
}

/**
 * One answer of the agent: its steps (reasoning, tool calls with their input and output,
 * the sources it used) drawn with shadcn's Trace, and its text between them, in the order
 * they came. Consecutive steps form one trace; text parts are the answer itself.
 */
export function AgentTurnView({ turn }: { turn: AgentTurn }) {
  const active = isActive(turn)
  const groups = groupParts(turn.parts)
  const lastIndex = lastPartIndex(turn.parts)
  return (
    <TurnShell model={turn.model} at={turn.created_at}>
      {groups.map((group) =>
        group.kind === 'text' ? (
          <div key={group.index} data-part="text">
            <Markdown streaming={active}>{group.part.text}</Markdown>
          </div>
        ) : (
          <Trace key={group.index} aria-label="Steps">
            {group.steps.map((step) =>
              step.kind === 'sources' ? (
                <SourcesRow key={step.index} sources={step.sources} />
              ) : step.part.type === 'reasoning' ? (
                <ReasoningRow key={step.index} part={step.part} running={active && step.index === lastIndex} />
              ) : (
                <ToolRow key={step.index} part={step.part} active={active} />
              ),
            )}
          </Trace>
        ),
      )}
      <TurnStatus turn={turn} hasParts={lastIndex >= 0} />
    </TurnShell>
  )
}

/** What the turn as a whole is doing, when its parts do not say it already. */
function TurnStatus({ turn, hasParts }: { turn: AgentTurn; hasParts: boolean }) {
  if (turn.status === 'queued') return <Waiting title="Waiting for the agent" />
  if (turn.status === 'running' && !hasParts) return <Waiting title="Thinking" />
  if (turn.status === 'failed')
    return (
      <Trace>
        <TraceLine status="error" role="alert">
          <TraceIcon>
            <CircleAlert />
          </TraceIcon>
          <TraceTitle className="whitespace-normal">The agent failed{turn.error ? `: ${turn.error}` : ''}</TraceTitle>
        </TraceLine>
      </Trace>
    )
  if (turn.status === 'cancelled')
    return (
      <Trace>
        <TraceLine>
          <TraceIcon>
            <CircleStop />
          </TraceIcon>
          <TraceTitle>Stopped</TraceTitle>
        </TraceLine>
      </Trace>
    )
  return null
}

function Waiting({ title }: { title: string }) {
  return (
    <Trace>
      <TraceLine status="running" role="status">
        <TraceIcon>
          <LoaderCircle className="animate-spin motion-reduce:animate-none" />
        </TraceIcon>
        <TraceTitle>{title}</TraceTitle>
      </TraceLine>
    </Trace>
  )
}

/** The agent's thinking: open while it streams, folded once it moved on. */
function ReasoningRow({ part, running }: { part: ReasoningPart; running: boolean }) {
  const [open, setOpen] = useState<boolean>()
  return (
    <TraceCollapsible open={open ?? running} onOpenChange={setOpen}>
      <TraceCollapsibleTrigger>
        <TraceLine status={running ? 'running' : undefined}>
          <TraceIcon>{running ? <LoaderCircle className="animate-spin motion-reduce:animate-none" /> : <Brain />}</TraceIcon>
          <TraceTitle>{running ? 'Thinking' : 'Thought'}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Markdown streaming={running} className="text-muted-foreground">
          {part.text}
        </Markdown>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

/** A tool call: its name and state on the line, its input and output (or error) inside. */
function ToolRow({ part, active }: { part: ToolPart; active: boolean }) {
  const name = part.tool_name
  const failed = part.state === 'output-error'
  // A call still waiting for its output when the turn ended never got one.
  const unfinished = part.state === 'input-available' && !active
  const running = part.state === 'input-available' && active
  const title = running ? `Calling ${name}` : failed ? `Failed: ${name}` : unfinished ? `Did not finish: ${name}` : `Called ${name}`
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine status={running ? 'running' : failed || unfinished ? 'error' : undefined}>
          <TraceIcon>
            {running ? (
              <LoaderCircle className="animate-spin motion-reduce:animate-none" />
            ) : failed || unfinished ? (
              <CircleAlert />
            ) : (
              <CircleCheck />
            )}
          </TraceIcon>
          <TraceTitle>{title}</TraceTitle>
          <TraceIcon>
            <Wrench />
          </TraceIcon>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="flex flex-col gap-2">
        <Json label="Input" value={part.input} />
        {failed ? (
          <Json label="Error" value={part.error_text ?? 'The tool failed without saying why.'} error />
        ) : part.state === 'output-available' ? (
          <Json label="Output" value={part.output} />
        ) : null}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

/** A JSON value under a caption, scrollable; red for an error. */
export function Json({ label, value, error = false }: { label: string; value: unknown; error?: boolean }) {
  const captionId = useId()
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return (
    <figure aria-labelledby={captionId} className="flex min-w-0 flex-col gap-1">
      <figcaption id={captionId} className="text-xs font-medium text-foreground">{label}</figcaption>
      <pre
        tabIndex={0}
        className={`max-h-64 overflow-auto rounded-md border px-2.5 py-2 font-mono text-xs whitespace-pre-wrap ${
          error ? 'border-destructive/30 text-destructive' : 'bg-muted/40'
        }`}
      >
        {text}
      </pre>
    </figure>
  )
}

/** The data sources the agent used: one line, opening into the list. */
function SourcesRow({ sources }: { sources: SourcePart[] }) {
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine>
          <TraceIcon>
            <Database />
          </TraceIcon>
          <TraceTitle>
            Used {sources.length} source{sources.length === 1 ? '' : 's'}
          </TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {sources.map((source) =>
            source.url ? (
              <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer">
                <TraceLine>
                  <TraceIcon>
                    <Database />
                  </TraceIcon>
                  <TraceTitle>
                    {source.title}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </TraceTitle>
                  <TraceIcon>
                    <ArrowUpRight />
                  </TraceIcon>
                </TraceLine>
              </a>
            ) : (
              <TraceLine key={source.source_id}>
                <TraceIcon>
                  <Database />
                </TraceIcon>
                <TraceTitle>{source.title}</TraceTitle>
                <TraceDescription className="font-mono">{source.source_id}</TraceDescription>
              </TraceLine>
            ),
          )}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

function lastPartIndex(parts: readonly (Part | undefined)[]): number {
  for (let index = parts.length - 1; index >= 0; index--) if (parts[index]) return index
  return -1
}
