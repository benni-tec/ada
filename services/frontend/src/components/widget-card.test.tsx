import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Widget } from '@/lib/api'
import { LiveContext } from '@/lib/live'

import { WidgetFrame } from './widget-card'

const widget = { id: 'w1', type: 'map', title: 'Screening' } as Widget

function frameAt(epoch: number, runId: string, runFollowsData: boolean) {
  return (
    <LiveContext.Provider value={{ connection: 'open', widgetEpoch: epoch }}>
      <WidgetFrame widget={widget} runId={runId} runFollowsData={runFollowsData} />
    </LiveContext.Provider>
  )
}

test('a frame reloads on the live epoch', () => {
  const { rerender } = render(frameAt(0, 'r1', false))
  const first = screen.getByTitle('Widget: Screening')
  rerender(frameAt(1, 'r1', false))
  expect(screen.getByTitle('Widget: Screening')).not.toBe(first)
})

test('a frame whose run follows the data reloads once, on the new run only', () => {
  const { rerender } = render(frameAt(0, 'r1', true))
  const first = screen.getByTitle('Widget: Screening')
  // The data changed: the epoch moves first, while the page starts the new run.
  rerender(frameAt(1, 'r1', true))
  expect(screen.getByTitle('Widget: Screening')).toBe(first)
  // The new run changes the address, which reloads the same frame.
  rerender(frameAt(1, 'r2', true))
  expect(screen.getByTitle('Widget: Screening')).toBe(first)
  expect(first.getAttribute('src')).toContain('run=r2')
})

test('a map frame is tall enough for a country', () => {
  render(frameAt(0, 'r1', false))
  expect(screen.getByTitle('Widget: Screening').parentElement).toHaveStyle({ height: '420px' })
})
