import type { Actor } from '@/lib/api'

const kindLabels: Record<Actor['kind'], string> = {
  user: 'Person',
  agent: 'Platform agent',
  external_agent: 'External agent',
  system: 'System',
}

/** "Person (web)", "Platform agent", or the client's name for an external agent. */
export function actorLabel(actor: Actor): string {
  if (actor.kind === 'external_agent') return actor.name || 'External agent'
  return actor.name ? `${kindLabels[actor.kind]} (${actor.name})` : kindLabels[actor.kind]
}
