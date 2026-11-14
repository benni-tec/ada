import { expect, test } from 'vitest'

import type { EventType } from '@/lib/api'

import { effectsOf } from './events'

function event(type: EventType, payload: Record<string, unknown>) {
  return effectsOf({ type, project_id: 'p1', payload, at: '2026-11-01T10:00:00Z' })
}

test('each event makes stale the queries of what it names', () => {
  const invalidated = (type: EventType, payload: Record<string, unknown>) => event(type, payload).invalidate
  expect(invalidated('session.created', { session_id: 's1' })).toEqual([['projects', 'p1', 'sessions']])
  expect(invalidated('session.entry_added', { session_id: 's1', entry_id: 'e1' })).toEqual([['sessions', 's1', 'entries']])
  expect(invalidated('widget.created', { widget_id: 'w1', session_id: 's1' })).toEqual([
    ['sessions', 's1', 'widgets'],
    ['projects', 'p1', 'widgets'],
    ['widgets', 'w1'],
    ['projects', 'p1', 'verdicts'],
  ])
  expect(invalidated('widget.created', { widget_id: 'w1' })).toEqual([
    ['projects', 'p1', 'widgets'],
    ['widgets', 'w1'],
    ['projects', 'p1', 'verdicts'],
  ])
  for (const type of ['run.started', 'run.finished', 'run.failed'] as const) {
    expect(invalidated(type, { run_id: 'r1', operator_id: 'op_1' })).toEqual([['runs', 'r1']])
  }
  expect(invalidated('dashboard.changed', { dashboard_id: 'd1', version_id: 'v2' })).toEqual([
    ['projects', 'p1', 'dashboards'],
    ['dashboards', 'd1'],
  ])
  expect(invalidated('report.version_created', { report_id: 'rep1', version_id: 'v3', version: '1.2.0' })).toEqual([
    ['projects', 'p1', 'reports'],
    ['reports', 'rep1'],
  ])
  expect(invalidated('alert.resolved', {})).toEqual([['alerts'], ['alert-rules']])
  // Payloads without ids invalidate nothing they cannot name.
  expect(invalidated('session.entry_added', {})).toEqual([])
})

test('a refresh reloads widgets only when data changed or became stale', () => {
  const sources = [
    ['projects', 'p1', 'sources'],
    ['sources', 'd1'],
  ]
  expect(event('source.refreshed', { data_source_id: 'd1', changed: true })).toEqual({ invalidate: sources, reloadWidgets: true })
  expect(event('source.refreshed', { data_source_id: 'd1', changed: false })).toEqual({ invalidate: sources, reloadWidgets: false })
  expect(event('source.refresh_failed', { data_source_id: 'd1', changed: false, error: 'HTTP 503' })).toEqual({
    invalidate: sources,
    reloadWidgets: true,
  })
  expect(event('dashboard.changed', { dashboard_id: 'd1' }).reloadWidgets).toBe(false)
})

test('an agent turn refreshes the record and the turn; a part goes into the cached turn as it is', () => {
  const both = [
    ['sessions', 's1', 'entries'],
    ['session-turns', 's1'],
    ['turns', 't1'],
  ]
  expect(event('agent.turn_started', { session_id: 's1', turn_id: 't1' })).toEqual({ invalidate: both, reloadWidgets: false })
  expect(event('agent.turn_finished', { session_id: 's1', turn_id: 't1', status: 'done' })).toMatchObject({
    invalidate: both,
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

test('a changed widget is read again and its frames reload', () => {
  const effects = event('widget.updated', { widget_id: 'w1', session_id: 's1' })
  expect(effects.invalidate).toEqual([
    ['sessions', 's1', 'widgets'],
    ['projects', 'p1', 'widgets'],
    ['widgets', 'w1'],
    // Its verdict may have changed: the judges' lists of the project.
    ['projects', 'p1', 'verdicts'],
  ])
  expect(effects.reloadWidgets).toBe(true)
  expect(event('widget.created', { widget_id: 'w1' }).reloadWidgets).toBe(false)
})
