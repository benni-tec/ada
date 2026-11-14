import type { QueryKey } from '@tanstack/react-query'

import { dashboardKeys, keys, type EventType, type LiveEvent } from '@/lib/api'

/** What the page does about one live event. */
export type Effects = {
  /** Query key prefixes to refetch. */
  invalidate: QueryKey[]
  /** Widget frames reload: the data behind them may have changed. Widgets fetch their own
   * data, so the query cache cannot see it. */
  reloadWidgets: boolean
}

/** Every type the stream may carry; one listener each, since named server-sent events
 * do not reach `onmessage`. */
export const EVENT_TYPES: readonly EventType[] = [
  'session.created',
  'session.entry_added',
  'widget.created',
  'run.started',
  'run.finished',
  'run.failed',
  'source.refreshed',
  'source.refresh_failed',
  'dashboard.changed',
  'report.version_created',
  'alert.firing',
  'alert.resolved',
]

function id(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key]
  return typeof value === 'string' && value !== '' ? value : null
}

/** Maps an event to the queries it makes stale. Payloads carry ids only, so the page
 * refetches what it shows instead of patching the cache. */
export function effectsOf(event: LiveEvent): Effects {
  const { payload, project_id: projectId } = event
  const invalidate: QueryKey[] = []
  let reloadWidgets = false

  switch (event.type) {
    case 'session.created':
      // E.g. an agent over MCP started one: the project page lists it.
      invalidate.push(keys.sessions(projectId))
      break
    case 'session.entry_added': {
      const session = id(payload, 'session_id')
      if (session) invalidate.push(keys.entries(session))
      break
    }
    case 'widget.created': {
      const session = id(payload, 'session_id')
      if (session) invalidate.push(keys.sessionWidgets(session))
      invalidate.push(keys.projectWidgets(projectId))
      const widget = id(payload, 'widget_id')
      if (widget) invalidate.push(keys.widget(widget))
      break
    }
    case 'run.started':
    case 'run.finished':
    case 'run.failed': {
      const run = id(payload, 'run_id')
      if (run) invalidate.push(keys.run(run))
      break
    }
    case 'source.refreshed':
    case 'source.refresh_failed': {
      invalidate.push(keys.sources(projectId))
      const source = id(payload, 'data_source_id')
      if (source) invalidate.push(keys.source(source))
      // New data changes what widgets show; a failure makes it stale, which they mark.
      reloadWidgets = event.type === 'source.refresh_failed' || payload.changed === true
      break
    }
    case 'dashboard.changed': {
      // Also created, or its time range changed: the project's list shows both.
      invalidate.push(dashboardKeys.list(projectId))
      const dashboard = id(payload, 'dashboard_id')
      if (dashboard) invalidate.push(keys.dashboard(dashboard))
      break
    }
    // Reports and alerts have no views yet (wave 2).
    case 'report.version_created':
    case 'alert.firing':
    case 'alert.resolved':
      break
  }
  return { invalidate, reloadWidgets }
}
