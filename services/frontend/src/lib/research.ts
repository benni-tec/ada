import type { AgentTurn } from '@/lib/api'

export type DelegationState = 'running' | 'done' | 'failed'

/** Where a delegation stands. It has no field of its own: it follows the research
 * session's latest turn. */
export function delegationState(turns: Pick<AgentTurn, 'status'>[]): DelegationState {
  const latest = turns.at(-1)?.status
  if (latest === 'failed' || latest === 'cancelled') return 'failed'
  return latest === 'done' ? 'done' : 'running'
}
