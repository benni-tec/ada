import { expect, test } from 'vitest'

import type { AgentTurn } from '@/lib/api'

import { delegationState } from './research'

const turn = (status: AgentTurn['status']) => ({ status }) as AgentTurn

test('a delegation runs while the research turn does or no turn exists, fails when it failed or was stopped, and is done once the report is in', () => {
  expect(delegationState([], false)).toBe('running')
  expect(delegationState([turn('queued')], false)).toBe('running')
  expect(delegationState([turn('done'), turn('running')], true)).toBe('running')
  // The turn is over but its report has not landed yet.
  expect(delegationState([turn('done')], false)).toBe('running')
  expect(delegationState([turn('done')], true)).toBe('done')
  expect(delegationState([turn('failed')], true)).toBe('failed')
  expect(delegationState([turn('cancelled')], false)).toBe('failed')
})
