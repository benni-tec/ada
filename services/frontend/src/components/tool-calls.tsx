import { CircleAlert, CircleCheck, EyeOff, Wrench } from 'lucide-react'

import { Json } from '@/components/chat/agent-turn'
import { Time } from '@/components/provenance'
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
import type { Actor } from '@/lib/api'
import { isExploration, type ToolCallEntry } from '@/lib/session-record'

/**
 * A run of one agent's tool calls in the record, folded into one line ("claude-code used
 * 6 tools"), drawn like the platform agent's steps. Opened, each call shows its tool, how
 * it went and how long it took; opened again, its arguments and error. Calls whose answers
 * are for the agent alone are marked: what it explored is not shown to the person.
 */
export function ToolCallGroup({ actor, calls }: { actor: Actor; calls: ToolCallEntry[] }) {
  const failed = calls.filter((call) => call.tool_call.status === 'error').length
  const who = actor.kind === 'external_agent' ? actor.name || 'An external agent' : actor.name || 'An agent'
  const external = actor.kind === 'external_agent'
  return (
    <div className={`border-l-2 py-1 pl-4 ${external ? 'border-violet-400 dark:border-violet-700' : 'border-border'}`}>
      <Trace aria-label={`Tool calls of ${who}`}>
        <TraceCollapsible>
          <TraceCollapsibleTrigger>
            <TraceLine status={failed ? 'error' : undefined}>
              <TraceIcon>
                <Wrench />
              </TraceIcon>
              <TraceTitle>
                {who} used {calls.length} tool{calls.length === 1 ? '' : 's'}
                {failed > 0 && `, ${failed} failed`}
              </TraceTitle>
              <TraceDescription>
                <Time value={calls[0].created_at} />
              </TraceDescription>
            </TraceLine>
          </TraceCollapsibleTrigger>
          <TraceCollapsibleContent>
            <Trace>
              {calls.map((call) => (
                <ToolCallRow key={call.id} call={call} />
              ))}
            </Trace>
          </TraceCollapsibleContent>
        </TraceCollapsible>
      </Trace>
    </div>
  )
}

function ToolCallRow({ call }: { call: ToolCallEntry }) {
  const { tool, status, error, duration_ms: duration, arguments: args } = call.tool_call
  const failed = status === 'error'
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine status={failed ? 'error' : undefined}>
          <TraceIcon>{failed ? <CircleAlert /> : <CircleCheck />}</TraceIcon>
          <TraceTitle className="font-mono text-xs">{failed ? `Failed: ${tool}` : tool}</TraceTitle>
          <TraceDescription>{formatDuration(duration)}</TraceDescription>
          {isExploration(tool) && (
            <TraceDescription className="inline-flex items-center gap-1 italic">
              <EyeOff aria-hidden="true" className="size-3" />
              explored, not shown
            </TraceDescription>
          )}
        </TraceLine>
      </TraceCollapsibleTrigger>
      {failed && error && <p className="mt-0.5 ml-6 text-xs whitespace-pre-wrap text-destructive">{error}</p>}
      <TraceCollapsibleContent className="flex flex-col gap-2">
        <Json label="Arguments" value={args} />
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}
