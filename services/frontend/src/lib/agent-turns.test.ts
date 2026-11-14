import { QueryClient } from '@tanstack/react-query'
import { afterEach, expect, test } from 'vitest'

import type { AgentTurn } from '@/lib/api'

import { applyPart, forgetLiveParts, groupParts, receivePart, withLiveParts } from './agent-turns'
import { effectsOf } from './events'

const turn = (parts: AgentTurn['parts']): AgentTurn => ({
  id: 't1',
  session_id: 's1',
  prompt_entry_id: 'e1',
  model: 'm',
  status: 'running',
  parts,
  error: null,
  created_at: '',
  finished_at: null,
})

afterEach(() => forgetLiveParts())

test('a part replaces the one at its index, and may arrive before those before it', () => {
  const first = applyPart(turn([{ type: 'text', text: 'He' }]), 0, { type: 'text', text: 'Hello' })
  expect(first.parts).toEqual([{ type: 'text', text: 'Hello' }])
  const gap = applyPart(first, 2, { type: 'reasoning', text: 'later' })
  expect(gap.parts).toHaveLength(3)
  expect(gap.parts[1]).toBeUndefined()
})

test('a fetched turn gets the streamed parts beyond what it had, until the turn is forgotten', () => {
  const client = new QueryClient()
  receivePart(client, 't1', 0, { type: 'text', text: 'stale' })
  receivePart(client, 't1', 1, { type: 'text', text: 'new' })
  // The stored turn has index 0 already: only index 1 is added.
  expect(withLiveParts(turn([{ type: 'text', text: 'stored' }])).parts).toEqual([
    { type: 'text', text: 'stored' },
    { type: 'text', text: 'new' },
  ])
  forgetLiveParts('t1')
  expect(withLiveParts(turn([])).parts).toEqual([])
})

test('the cached turn takes a part at once', () => {
  const client = new QueryClient()
  client.setQueryData(['turns', 't1'], turn([]))
  receivePart(client, 't1', 0, { type: 'text', text: 'Hi' })
  expect(client.getQueryData<AgentTurn>(['turns', 't1'])?.parts).toEqual([{ type: 'text', text: 'Hi' }])
})

test('parts are grouped: text alone, steps together, neighbouring sources as one', () => {
  const groups = groupParts([
    { type: 'reasoning', text: 'r' },
    { type: 'source', source_id: 'a', title: 'A', url: null },
    { type: 'source', source_id: 'b', title: 'B', url: null },
    { type: 'text', text: 'answer' },
    undefined,
    { type: 'text', text: '' },
  ])
  expect(groups.map((group) => group.kind)).toEqual(['steps', 'text'])
  const steps = groups[0].kind === 'steps' ? groups[0].steps : []
  expect(steps.map((step) => step.kind)).toEqual(['part', 'sources'])
  expect(steps[1].kind === 'sources' && steps[1].sources.map((source) => source.title)).toEqual(['A', 'B'])
})

const event = (type: Parameters<typeof effectsOf>[0]['type'], payload: Record<string, unknown>) =>
  effectsOf({ type, project_id: 'p1', payload, at: '' })

test('an agent turn refreshes the record and the turn; a part is applied as it is', () => {
  expect(event('agent.turn_started', { session_id: 's1', turn_id: 't1' })).toEqual({
    invalidate: [
      ['sessions', 's1', 'entries'],
      ['turns', 't1'],
    ],
    reloadWidgets: false,
  })
  expect(event('agent.turn_finished', { session_id: 's1', turn_id: 't1', status: 'done' })).toMatchObject({
    invalidate: [
      ['sessions', 's1', 'entries'],
      ['turns', 't1'],
    ],
    turnFinished: 't1',
  })
  const part = { type: 'text', text: 'Hello' }
  expect(event('agent.turn_part', { session_id: 's1', turn_id: 't1', index: 2, part })).toEqual({
    invalidate: [],
    reloadWidgets: false,
    turnPart: { turnId: 't1', index: 2, part },
  })
  // A part without its index cannot be placed.
  expect(event('agent.turn_part', { session_id: 's1', turn_id: 't1', part }).turnPart).toBeUndefined()
})
