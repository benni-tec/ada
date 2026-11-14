import type { AgentTurn } from '@/lib/api'

export type DelegationState = 'running' | 'done' | 'failed'

/**
 * Where a delegation stands. It has no field of its own: it follows the research session's
 * latest turn, and is done only once the report has reached the parent (a finished turn
 * posts one, even when the agent forgot to).
 */
export function delegationState(turns: Pick<AgentTurn, 'status'>[], reported: boolean): DelegationState {
  const latest = turns.at(-1)?.status
  if (latest === 'failed' || latest === 'cancelled') return 'failed'
  return latest === 'done' && reported ? 'done' : 'running'
}
