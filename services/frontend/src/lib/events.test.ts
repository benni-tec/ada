import { expect, test } from 'vitest'

import type { EventType } from '@/lib/api'

import { effectsOf } from './events'

function event(type: EventType, payload: Record<string, unknown>) {
  return effectsOf({ type, project_id: 'p1', payload, at: '2026-11-01T10:00:00Z' })
}

test('a new session refreshes the session list', () => {
  expect(event('session.created', { session_id: 's1' })).toEqual({
    invalidate: [['projects', 'p1', 'sessions']],
    reloadWidgets: false,
  })
})

test('a new entry refreshes the session record', () => {
  expect(event('session.entry_added', { session_id: 's1', entry_id: 'e1' })).toEqual({
    invalidate: [['sessions', 's1', 'entries']],
    reloadWidgets: false,
  })
})

test('a new widget refreshes its session’s widgets and the project’s', () => {
  expect(event('widget.created', { widget_id: 'w1', session_id: 's1' }).invalidate).toEqual([
    ['sessions', 's1', 'widgets'],
    ['projects', 'p1', 'widgets'],
    ['widgets', 'w1'],
  ])
  expect(event('widget.created', { widget_id: 'w1' }).invalidate).toEqual([
    ['projects', 'p1', 'widgets'],
    ['widgets', 'w1'],
  ])
})

test('runs refresh the run', () => {
  for (const type of ['run.started', 'run.finished', 'run.failed'] as const) {
    expect(event(type, { run_id: 'r1', operator_id: 'op_1' })).toEqual({
      invalidate: [['runs', 'r1']],
      reloadWidgets: false,
    })
  }
})

test('a refresh reloads widgets only when data changed or became stale', () => {
  const sources = [
    ['projects', 'p1', 'sources'],
    ['sources', 'd1'],
  ]
  expect(event('source.refreshed', { data_source_id: 'd1', changed: true })).toEqual({
    invalidate: sources,
    reloadWidgets: true,
  })
  expect(event('source.refreshed', { data_source_id: 'd1', changed: false })).toEqual({
    invalidate: sources,
    reloadWidgets: false,
  })
  expect(event('source.refresh_failed', { data_source_id: 'd1', changed: false, error: 'HTTP 503' })).toEqual({
    invalidate: sources,
    reloadWidgets: true,
  })
})

test('payloads without ids invalidate nothing they cannot name', () => {
  expect(event('session.entry_added', {}).invalidate).toEqual([])
})
