import type { QueryClient } from '@tanstack/react-query'

import type { AgentTurn, Id, Part, ReasoningPart, SourcePart, TextPart, ToolPart } from '@/lib/api'

// An agent turn streams: each `agent.turn_part` event carries a whole part at an index,
// which replaces the part at that index (the text so far, a tool call's next state). It
// is the one event with content, since token deltas cannot be fetched afterwards.
//
// The turn in the query cache gets each part as it comes. A fetch of the turn, though,
// returns only what the backend has stored, which can be behind the stream: a refetch
// that resolves after some parts arrived would drop them. So the parts of turns still
// running are also kept here, and every fetched turn gets those with a higher index than
// it has (the contract's rule for a client that connects late). They are forgotten when
// the turn finishes (its stored form is then complete) and on a reconnect, when events
// were missed and the turn is fetched again anyway.
const live = new Map<Id, Map<number, Part>>()

/** The turn with `part` at `index`, replacing what was there. */
export function applyPart(turn: AgentTurn, index: number, part: Part): AgentTurn {
  const parts = [...turn.parts]
  parts[index] = part
  return { ...turn, parts }
}

/** A part from the live stream: into the cached turn, and kept for the next fetch of it. */
export function receivePart(queryClient: QueryClient, turnId: Id, index: number, part: Part) {
  const parts = live.get(turnId) ?? new Map<number, Part>()
  parts.set(index, part)
  live.set(turnId, parts)
  // A turn not in the cache yet takes the part when it is fetched (withLiveParts).
  // The key is agentKeys.turn, written out: importing it would make the modules a cycle.
  queryClient.setQueryData<AgentTurn>(['turns', turnId], (turn) => turn && applyPart(turn, index, part))
}

/** A fetched turn, with the parts the stream brought beyond what was stored. */
export function withLiveParts(turn: AgentTurn): AgentTurn {
  const parts = live.get(turn.id)
  if (!parts) return turn
  let result = turn
  for (const [index, part] of parts) if (index >= turn.parts.length) result = applyPart(result, index, part)
  return result
}

/** Forgets the streamed parts of one turn, or of all (on a reconnect). */
export function forgetLiveParts(turnId?: Id) {
  if (turnId === undefined) live.clear()
  else live.delete(turnId)
}

/** Whether the agent is still at it: the composer offers to stop it then. */
export function isActive(turn: Pick<AgentTurn, 'status'> | undefined): boolean {
  return turn?.status === 'queued' || turn?.status === 'running'
}

export type Step =
  | { kind: 'part'; index: number; part: ReasoningPart | ToolPart }
  | { kind: 'sources'; index: number; sources: SourcePart[] }
export type Group = { kind: 'text'; index: number; part: TextPart } | { kind: 'steps'; index: number; steps: Step[] }

/** The parts in order: text on its own, steps together, neighbouring sources as one line. */
export function groupParts(parts: readonly (Part | undefined)[]): Group[] {
  const groups: Group[] = []
  parts.forEach((part, index) => {
    if (!part) return
    if (part.type === 'text') {
      if (part.text !== '') groups.push({ kind: 'text', index, part })
      return
    }
    let group = groups.at(-1)
    if (group?.kind !== 'steps') {
      group = { kind: 'steps', index, steps: [] }
      groups.push(group)
    }
    const last = group.steps.at(-1)
    if (part.type === 'source') {
      if (last?.kind === 'sources') last.sources.push(part)
      else group.steps.push({ kind: 'sources', index, sources: [part] })
    } else group.steps.push({ kind: 'part', index, part })
  })
  return groups
}

