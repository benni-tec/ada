import type { QueryKey } from '@tanstack/react-query'

import {
  agentKeys,
  alertKeys,
  attachmentKeys,
  dashboardKeys,
  judgeKeys,
  keys,
  reportKeys,
  type EventType,
  type LiveEvent,
  type Part,
} from '@/lib/api'

/** What the page does about one live event. */
export type Effects = {
  /** Query key prefixes to refetch. */
  invalidate: QueryKey[]
  /** Widget frames reload: the data behind them may have changed. Widgets fetch their own
   * data, so the query cache cannot see it. */
  reloadWidgets: boolean
  /** A part of an agent turn, to put into the turn as it is: the one event with content. */
  turnPart?: { turnId: string; index: number; part: Part }
  /** An agent turn that finished: what was streamed of it can be forgotten. */
  turnFinished?: string
}

/** Every type the stream may carry; one listener each, since named server-sent events
 * do not reach `onmessage`. */
export const EVENT_TYPES: readonly EventType[] = [
  'session.created',
  'session.entry_added',
  'session.attachment_added',
  'session.attachment_removed',
  'widget.created',
  'widget.updated',
  'run.started',
  'run.finished',
  'run.failed',
  'source.refreshed',
  'source.refresh_failed',
  'dashboard.changed',
  'report.version_created',
  'project.order_changed',
  'alert.firing',
  'alert.resolved',
  'agent.turn_started',
  'agent.turn_part',
  'agent.turn_finished',
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
  const effects: Effects = { invalidate, reloadWidgets }

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
    case 'session.attachment_added':
    case 'session.attachment_removed': {
      // The session page's tabs; it opens one an agent added (components/attachments). The
      // project overview names what each recent session shows.
      const session = id(payload, 'session_id')
      if (session) invalidate.push(attachmentKeys.list(session))
      break
    }
    case 'widget.updated':
    case 'widget.created': {
      // A changed spec or type is read by the frames when they load. A frame's own report
      // of how it drew changes only the cards' error line: reloading would draw again,
      // report again, and never stop when each error reads differently.
      if (event.type === 'widget.updated' && payload.render_only !== true) reloadWidgets = true
      const session = id(payload, 'session_id')
      if (session) invalidate.push(keys.sessionWidgets(session))
      invalidate.push(keys.projectWidgets(projectId))
      const widget = id(payload, 'widget_id')
      if (widget) invalidate.push(keys.widget(widget))
      // A review's verdict arrives as an update; the judges' lists show it.
      invalidate.push(judgeKeys.verdicts(projectId))
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
    case 'report.version_created': {
      // The project's list, and the report's record and versions (a new latest version).
      invalidate.push(reportKeys.reports(projectId))
      const report = id(payload, 'report_id')
      if (report) invalidate.push(reportKeys.report(report))
      break
    }
    case 'project.order_changed':
      // Someone put the dashboards or the reports in a new order: the sidebar lists them.
      if (payload.list === 'dashboards') invalidate.push(dashboardKeys.list(projectId))
      if (payload.list === 'reports') invalidate.push(reportKeys.reports(projectId))
      break
    // The payload names the alert and rule only, so every alert view refetches (feed,
    // badges); rules show when they were last checked.
    case 'alert.firing':
    case 'alert.resolved':
      invalidate.push(alertKeys.all(), alertKeys.rules())
      break
    case 'agent.turn_started':
    case 'agent.turn_finished': {
      // The record gains the turn's entry (or the agent's operators and widgets), and the
      // turn its status; when it finished, its stored form is complete.
      const session = id(payload, 'session_id')
      if (session) invalidate.push(keys.entries(session), agentKeys.sessionTurns(session))
      const turn = id(payload, 'turn_id')
      if (turn) invalidate.push(agentKeys.turn(turn))
      if (turn && event.type === 'agent.turn_finished') effects.turnFinished = turn
      break
    }
    case 'agent.turn_part': {
      const turn = id(payload, 'turn_id')
      const { index, part } = payload
      if (turn && typeof index === 'number' && part && typeof part === 'object')
        effects.turnPart = { turnId: turn, index, part: part as Part }
      break
    }
  }
  effects.reloadWidgets = reloadWidgets
  return effects
}
