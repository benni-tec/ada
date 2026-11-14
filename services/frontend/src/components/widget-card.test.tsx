import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Widget } from '@/lib/api'
import { LiveContext } from '@/lib/live'
import { ThemeContext } from '@/lib/theme-context'

import { WidgetFrame } from './widget-card'

const widget = { id: 'w1', type: 'map', title: 'Screening' } as Widget

function frameAt(epoch: number, runId: string, reloadOnData: boolean) {
  return (
    <LiveContext.Provider value={{ connection: 'open', widgetEpoch: epoch }}>
      <WidgetFrame widget={widget} runId={runId} reloadOnData={reloadOnData} />
    </LiveContext.Provider>
  )
}

test('a frame reloads on the live epoch', () => {
  const { rerender } = render(frameAt(0, 'r1', true))
  const first = screen.getByTitle('Widget: Screening')
  rerender(frameAt(1, 'r1', true))
  expect(screen.getByTitle('Widget: Screening')).not.toBe(first)
})

test('a frame whose run follows the data reloads once, on the new run only', () => {
  const { rerender } = render(frameAt(0, 'r1', false))
  const first = screen.getByTitle('Widget: Screening')
  // The data changed: the epoch moves first, while the page starts the new run.
  rerender(frameAt(1, 'r1', false))
  expect(screen.getByTitle('Widget: Screening')).toBe(first)
  // The new run changes the address, which reloads the same frame.
  rerender(frameAt(1, 'r2', false))
  expect(screen.getByTitle('Widget: Screening')).toBe(first)
  expect(first.getAttribute('src')).toContain('run=r2')
})

test('a frame pinned to a run, as in a report, ignores data changes', () => {
  const { rerender } = render(frameAt(0, 'r1', false))
  const first = screen.getByTitle('Widget: Screening')
  rerender(frameAt(5, 'r1', false))
  expect(screen.getByTitle('Widget: Screening')).toBe(first)
  expect(first.getAttribute('src')).toContain('run=r1')
})

test('a map frame is tall enough for a country', () => {
  render(frameAt(0, 'r1', true))
  expect(screen.getByTitle('Widget: Screening').parentElement).toHaveStyle({ height: '420px' })
})

test('a theme picked apart from the system’s goes to the frame, which cannot see the page’s', () => {
  const frame = (theme: 'light' | 'dark' | 'system', resolved: 'light' | 'dark') => (
    <ThemeContext value={{ theme, resolved, setTheme: () => {} }}>{frameAt(0, 'r1', false)}</ThemeContext>
  )
  const { rerender } = render(frame('system', 'dark'))
  const element = screen.getByTitle('Widget: Screening')
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1')
  rerender(frame('light', 'light'))
  // The same frame, its fragment changed: no reload.
  expect(screen.getByTitle('Widget: Screening')).toBe(element)
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1&theme=light')
})
