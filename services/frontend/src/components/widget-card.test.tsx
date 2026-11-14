import { act, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

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

test('a frame reloads on the live epoch only if it does not follow a run; else once, on the new run', () => {
  const live = render(frameAt(0, 'r1', true))
  const first = screen.getByTitle('Widget: Screening')
  live.rerender(frameAt(1, 'r1', true))
  expect(screen.getByTitle('Widget: Screening')).not.toBe(first)
  live.unmount()

  const { rerender } = render(frameAt(0, 'r1', false))
  const frame = screen.getByTitle('Widget: Screening')
  // The data changed: the epoch moves first, while the page starts the new run.
  rerender(frameAt(1, 'r1', false))
  expect(screen.getByTitle('Widget: Screening')).toBe(frame)
  expect(frame.getAttribute('src')).toContain('run=r1')
  // The new run changes the address, which reloads the same frame.
  rerender(frameAt(1, 'r2', false))
  expect(screen.getByTitle('Widget: Screening')).toBe(frame)
  expect(frame.getAttribute('src')).toContain('run=r2')
})

test('a theme picked apart from the system’s goes to the frame, which cannot see the page’s', () => {
  const frame = (theme: 'light' | 'dark' | 'system', resolved: 'light' | 'dark') => (
    <ThemeContext value={{ theme, resolved, setTheme: () => {} }}>{frameAt(0, 'r1', false)}</ThemeContext>
  )
  const { rerender } = render(frame('system', 'dark'))
  const element = screen.getByTitle('Widget: Screening')
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1&fit=content')
  rerender(frame('light', 'light'))
  // The same frame, its fragment changed: no reload.
  expect(screen.getByTitle('Widget: Screening')).toBe(element)
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1&theme=light&fit=content')
})

test('a frame in a report or a session follows the height its widget posts; one with a height of its own does not', () => {
  const opened = vi.fn()
  const { rerender } = render(<WidgetFrame widget={widget} runId="r1" onOpenPipeline={opened} />)
  const frame = screen.getByTitle('Widget: Screening') as HTMLIFrameElement
  const box = frame.parentElement!
  // The map's usual height until the widget says.
  expect(box).toHaveStyle({ height: '420px' })
  const post = (data: unknown, source: MessageEventSource | null = frame.contentWindow) =>
    act(() => window.dispatchEvent(new MessageEvent('message', { data, source })))

  post({ type: 'ada:resize', height: 512.3 })
  expect(box).toHaveStyle({ height: '513px' })
  // Within bounds: never collapsed, never longer than the limit.
  post({ type: 'ada:resize', height: 0 })
  expect(box).toHaveStyle({ height: '64px' })
  post({ type: 'ada:resize', height: 99_999 })
  expect(box).toHaveStyle({ height: '2400px' })
  // Only its own frame speaks for it.
  post({ type: 'ada:resize', height: 300 }, window)
  expect(box).toHaveStyle({ height: '2400px' })

  post({ type: 'ada:open-pipeline', input: 'gap' })
  expect(opened).toHaveBeenCalledWith('gap')

  // A widget's page: a fixed height, the widget fills it.
  rerender(<WidgetFrame widget={widget} runId="r1" tall />)
  const tall = screen.getByTitle('Widget: Screening') as HTMLIFrameElement
  expect(tall.getAttribute('src')).not.toContain('fit=content')
  act(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'ada:resize', height: 100 }, source: tall.contentWindow })))
  expect(tall.parentElement).toHaveStyle({ height: '735px' })
})
