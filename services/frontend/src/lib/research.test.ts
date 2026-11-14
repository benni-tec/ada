import { expect, test } from 'vitest'

import type { AgentTurn } from '@/lib/api'

import { delegationState } from './research'

const turn = (status: AgentTurn['status']) => ({ status }) as AgentTurn

test('a delegation runs while the research turn does or none exists, is done when it is, and fails when it failed or was stopped', () => {
  expect(delegationState([])).toBe('running')
  expect(delegationState([turn('queued')])).toBe('running')
  expect(delegationState([turn('done'), turn('running')])).toBe('running')
  expect(delegationState([turn('done')])).toBe('done')
  expect(delegationState([turn('failed')])).toBe('failed')
  expect(delegationState([turn('cancelled')])).toBe('failed')
})
