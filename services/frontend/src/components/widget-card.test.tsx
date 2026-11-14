import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { Verdict, Widget } from '@/lib/api'
import { LiveContext } from '@/lib/live'
import { ThemeContext } from '@/lib/theme-context'

import { TooltipProvider } from '@/components/ui/tooltip'

import { VerdictBadge } from './verdict-badge'
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

function verdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    kind: 'text_widget',
    outcome: 'pass',
    passed: true,
    blocking: false,
    findings: [],
    model: 'gemini/pro',
    reason: null,
    content_hash: 'sha256:1',
    checked_at: '2026-11-14T10:00:00Z',
    ...overrides,
  }
}

function badge(value: Verdict | null) {
  const text = { id: 'w9', project_id: 'p1', type: 'text', title: 'Why', verdict: value } as Widget
  return (
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <VerdictBadge widget={text} runId="r1" />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

test('the verdict badge says how the review went in words and an icon, never colour alone', () => {
  const warning = { message: 'Cannot tell', excerpt: 'more than before', severity: 'warning' as const }
  const error = { message: 'No input backs 13.2', excerpt: 'a gap of 13.2', severity: 'error' as const }
  const { rerender } = render(badge(verdict()))
  expect(screen.getByRole('button')).toHaveTextContent('Reviewed ✓')
  rerender(badge(verdict({ outcome: 'warn', findings: [warning] })))
  expect(screen.getByRole('button')).toHaveTextContent('1 finding')
  rerender(badge(verdict({ outcome: 'fail', passed: false, findings: [warning, error] })))
  expect(screen.getByRole('button')).toHaveTextContent('Failed: 2 findings')
  expect(screen.getByRole('button').querySelector('svg')).toBeInTheDocument()
  rerender(badge(verdict({ outcome: 'unchecked', passed: false, model: null, reason: 'No model is chosen for this judge' })))
  expect(screen.getByRole('button')).toHaveTextContent('Not reviewed')
  rerender(badge(null))
  expect(screen.getByRole('button')).toHaveTextContent('Not reviewed')
})

test('the badge opens the findings, errors first, or why it was not reviewed', async () => {
  const warning = { message: 'Cannot tell', excerpt: 'more than before', severity: 'warning' as const }
  const error = { message: 'No input backs 13.2', excerpt: 'a gap of 13.2', severity: 'error' as const }
  const { unmount } = render(badge(verdict({ outcome: 'fail', passed: false, blocking: true, findings: [warning, error] })))
  fireEvent.click(screen.getByRole('button', { name: /Failed/ }))
  const findings = await screen.findByRole('list', { name: 'Findings' })
  expect(within(findings).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'Errora gap of 13.2No input backs 13.2',
    'Warningmore than beforeCannot tell',
  ])
  expect(screen.getByText(/stops report versions/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Review again' })).toBeInTheDocument()
  unmount()

  render(badge(verdict({ outcome: 'unchecked', passed: false, model: null, reason: 'No model is chosen for this judge' })))
  fireEvent.click(screen.getByRole('button', { name: /Not reviewed/ }))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('No model is chosen for this judge')
  expect(within(dialog).queryByRole('list', { name: 'Findings' })).not.toBeInTheDocument()
})

test('a custom widget’s card says what went wrong drawing it, and its badge what the code review found', () => {
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
  const client = new QueryClient()
  const card = (shown: Widget) => (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <WidgetCard widget={shown} run={{ id: 'r1', frozen: true, what: 'report version 1.0.0' }} openable={false} actions={<></>} />
      </TooltipProvider>
    </QueryClientProvider>
  )
  const { rerender } = render(card(custom))
  const article = screen.getByRole('article', { name: 'Coverage against targets' })
  expect(within(article).getByText('custom')).toBeInTheDocument()
  expect(within(article).getByText('Not drawn: data.main.rows[0].cases is undefined (line 4)')).toBeInTheDocument()

  // The judges' badge shows the review, as for a text widget.
  expect(within(article).getByRole('button', { name: /1 finding/ })).toBeInTheDocument()

  // Drawn: the error line goes.
  rerender(card({ ...custom, render_error: null }))
  expect(screen.queryByText(/Not drawn/)).not.toBeInTheDocument()
})
