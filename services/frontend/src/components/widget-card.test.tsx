import { act, render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import type { Widget } from '@/lib/api'
import { LiveContext } from '@/lib/live'
import { ThemeContext } from '@/lib/theme-context'

import { WidgetCard, WidgetFrame } from './widget-card'

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
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1')
  rerender(frame('light', 'light'))
  // The same frame, its fragment changed: no reload.
  expect(screen.getByTitle('Widget: Screening')).toBe(element)
  expect(element.getAttribute('src')).toBe('http://localhost:5174/map.html#widget=w1&run=r1&theme=light')
})

test('a custom widget’s card says what went wrong drawing it, and warns with what the code review found', async () => {
  const custom: Widget = {
    id: 'w2',
    project_id: 'p1',
    operator_id: 'op_1',
    type: 'custom',
    title: 'Coverage against targets',
    spec: { code: 'export default function render() {}' },
    note: '',
    inputs: {},
    created_by: { kind: 'user', name: 'web' },
    created_at: '2026-11-14T09:00:00Z',
    render_error: 'data.main.rows[0].cases is undefined (line 4)',
    verdict: {
      kind: 'widget_code',
      outcome: 'warn',
      passed: true,
      blocking: false,
      findings: [{ message: 'A target is written into the code', excerpt: 'const target = 90', severity: 'warning' }],
      model: 'anthropic/claude',
      content_hash: 'h1',
      checked_at: '2026-11-14T10:00:00Z',
    },
  }
  const card = (shown: Widget) => (
    <TooltipProvider>
      <WidgetCard widget={shown} run={{ id: 'r1', frozen: true, what: 'report version 1.0.0' }} openable={false} actions={<></>} />
    </TooltipProvider>
  )
  const { rerender } = render(card(custom))
  const article = screen.getByRole('article', { name: 'Coverage against targets' })
  expect(within(article).getByText('custom')).toBeInTheDocument()
  expect(within(article).getByText('Not drawn: data.main.rows[0].cases is undefined (line 4)')).toBeInTheDocument()

  const warning = within(article).getByRole('button', { name: 'The code review warns: 1 finding' })
  act(() => warning.focus())
  const tooltip = await screen.findByRole('tooltip')
  expect(tooltip).toHaveTextContent('A target is written into the code')
  expect(tooltip).toHaveTextContent('const target = 90')

  // Drawn, and not reviewed: neither shows.
  rerender(card({ ...custom, render_error: null, verdict: { ...custom.verdict!, outcome: 'unchecked', findings: [] } }))
  expect(screen.queryByText(/Not drawn/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /code review/ })).not.toBeInTheDocument()
})
