import type { Actor, SessionEntry, ToolCall } from '@/lib/api'

/** A tool call entry, with its call. */
export type ToolCallEntry = SessionEntry & { tool_call: ToolCall }

/** What the session record draws: one entry, or a run of one actor's tool calls. */
export type RecordItem =
  | { kind: 'entry'; entry: SessionEntry }
  | { kind: 'tool-calls'; key: string; actor: Actor; calls: ToolCallEntry[] }

/** Tools that put what they made into the record themselves, as an operator or widget. */
const RECORDING_TOOLS = new Set([
  'add_source_operator',
  'add_transform',
  'add_statistic',
  'create_widget',
  'build_pipeline',
])

/** Calls whose answers are for the agent alone: it may not show them to the person. */
const EXPLORATION_TOOLS = new Set(['query_operator', 'search_web', 'read_page', 'extract_table', 'map_site'])

export function isExploration(tool: string): boolean {
  return EXPLORATION_TOOLS.has(tool)
}

export function isToolCall(entry: SessionEntry): entry is ToolCallEntry {
  return entry.kind === 'tool_call' && !!entry.tool_call
}

/**
 * The record as it is drawn: consecutive tool calls of one actor fold into one group. A
 * call is recorded after it ran, so right after the operator or widget entries of what it
 * made; a successful call of a tool that records those is left out, since its entries
 * already show it. Calls it left out do not split a group.
 */
export function groupRecord(entries: readonly SessionEntry[]): RecordItem[] {
  const items: RecordItem[] = []
  let previous: SessionEntry | undefined
  for (const entry of entries) {
    if (isToolCall(entry)) {
      if (!shownByItsEntries(entry, previous)) {
        const last = items.at(-1)
        if (last?.kind === 'tool-calls' && sameActor(last.actor, entry.actor)) last.calls.push(entry)
        else items.push({ kind: 'tool-calls', key: entry.id, actor: entry.actor, calls: [entry] })
      }
    } else {
      items.push({ kind: 'entry', entry })
    }
    previous = entry
  }
  return items
}

function shownByItsEntries(call: ToolCallEntry, previous: SessionEntry | undefined): boolean {
  return (
    call.tool_call.status === 'ok' &&
    RECORDING_TOOLS.has(call.tool_call.tool) &&
    !!previous &&
    (previous.kind === 'operator' || previous.kind === 'widget') &&
    sameActor(previous.actor, call.actor)
  )
}

function sameActor(a: Actor, b: Actor): boolean {
  return a.kind === b.kind && a.name === b.name
}
