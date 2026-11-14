import type { ReactNode } from 'react'

import type { Id } from '@/lib/api'
import { LiveContext, useLive, useProjectEvents, type Connection } from '@/lib/live'

/** Opens the project's live stream for everything rendered inside it. */
export function ProjectLive({ projectId, children }: { projectId: Id; children: ReactNode }) {
  const live = useProjectEvents(projectId)
  return <LiveContext value={live}>{children}</LiveContext>
}

const labels: Record<Connection, string> = {
  connecting: 'Connecting',
  open: 'Live',
  reconnecting: 'Reconnecting',
}

/** A dot and a word: whether this page updates by itself right now. */
export function ConnectionIndicator() {
  const { connection } = useLive()
  return (
    <span
      role="status"
      aria-label={`Live updates: ${labels[connection]}`}
      title={connection === 'open' ? 'This page updates as the project changes' : 'Changes may not show until reconnected'}
      className="inline-flex items-center gap-1.5 text-xs text-neutral-600 dark:text-neutral-400"
    >
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${
          connection === 'open' ? 'bg-green-600 dark:bg-green-400' : 'animate-pulse bg-amber-500 dark:bg-amber-400'
        }`}
      />
      {labels[connection]}
    </span>
  )
}
