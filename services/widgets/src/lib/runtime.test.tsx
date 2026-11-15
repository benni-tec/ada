import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { coverage, widget } from '@/test/samples'
import { Any } from '@/widgets/any/any'

import { fetchAll, followFit, followTheme, reportHeight } from './host'
import { WidgetRuntime } from './runtime'
import type { WidgetData } from './types'

// A widget loads itself from its address in our frontend, or from its MCP host.

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Answers the two requests a widget makes. */
function serve({ data = coverage() } = {} as { data?: WidgetData }) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/widgets/w1/data')) return json(data)
    if (url === '/api/widgets/w1') return json(widget())
    return json({ detail: 'unexpected' }, 500)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function show(hash = '#widget=w1') {
  window.location.hash = hash
  render(<WidgetRuntime>{({ data, roles }) => <p>{`${data.rows.length} rows, ${roles.measures?.length ?? 0} measures`}</p>}</WidgetRuntime>)
}

test('loads the widget, its data and its roles from the fragment', async () => {
  const fetch = serve({ data: coverage({ output: { columns: [] } }) })
  show('#widget=w1&run=r9')

  expect(screen.getByRole('status')).toHaveTextContent('Loading')
  // An output that declares no roles has none.
  expect(await screen.findByText('6 rows, 0 measures')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/widgets/w1/data?limit=1000&run_id=r9')
  expect(screen.queryByRole('list', { name: 'Data warnings' })).not.toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Sources' })).not.toBeInTheDocument()
})

test('names the source and its fetch time under the numbers', async () => {
  serve({
    data: coverage({
      sources: [{ operator_id: 'op1', name: 'Kainuu', address: 'https://example.test/k', fetched_at: '2026-11-14T10:00:00Z' }],
    }),
  })
  show()

  const sources = await screen.findByRole('list', { name: 'Sources' })
  expect(within(sources).getByRole('link', { name: 'Kainuu' })).toHaveAttribute('href', 'https://example.test/k')
  expect(sources).toHaveTextContent(/fetched .*2026/)
})

test('lists the first two sources and points to the pipeline for the rest', async () => {
  const source = (n: number) => ({ operator_id: `op${n}`, name: `Source ${n}`, address: 'x', fetched_at: null })
  serve({ data: coverage({ sources: [1, 2, 3, 4].map(source) }) })
  show()

  const sources = await screen.findByRole('list', { name: 'Sources' })
  const items = within(sources).getAllByRole('listitem').map((item) => item.textContent)
  expect(items).toEqual([
    expect.stringContaining('Source 1'),
    expect.stringContaining('Source 2'),
    'and 2 more: the Pipeline, under the widget, lists every source',
  ])
})

test('a custom widget lists each source once, with the fetch time any input knows', async () => {
  const fixed = { operator_id: 'op2', name: 'Kainuu', address: 'https://example.test/k', fetched_at: '2026-11-14T10:00:00Z' }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://ada.test')
      if (url.pathname === '/api/widgets/w1') return json(widget({ type: 'custom', inputs: { gap: 'op_2' } }))
      // The gap input has not read Kainuu, so its answer has no fetch time for it.
      const sources = url.searchParams.get('input') === 'gap' ? [{ ...fixed, fetched_at: null }] : [fixed]
      return json(coverage({ sources }))
    }),
  )
  show()

  const sources = await screen.findByRole('list', { name: 'Sources' })
  expect(within(sources).getAllByRole('listitem')).toHaveLength(1)
  expect(sources).toHaveTextContent(/fetched .*2026/)
})

test('marks stale data, but not a run that binds inputs', async () => {
  serve({ data: coverage({ is_scenario: true, is_stale: true }) })
  show()

  expect(await screen.findByText('6 rows, 1 measures')).toBeInTheDocument()
  const flags = screen.getByRole('list', { name: 'Data warnings' })
  expect(within(flags).getAllByRole('listitem').map((flag) => flag.textContent)).toEqual([
    'Stale: last good data, a refresh failed',
  ])
  expect(screen.queryByText(/scenario|simulated/i)).not.toBeInTheDocument()
})

test('shows no warnings for a run that only binds inputs', async () => {
  serve({ data: coverage({ is_scenario: true }) })
  show()

  expect(await screen.findByText('6 rows, 1 measures')).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Data warnings' })).not.toBeInTheDocument()
})

test('shows the server error, or that the address names no widget', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ detail: 'Widget w1 not found' }, 404)),
  )
  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Widget w1 not found')
  cleanup()

  serve()
  show('')
  expect(await screen.findByRole('alert')).toHaveTextContent('names no widget')
})

// Inside an MCP host

type Sent = { jsonrpc: string; id?: number; method: string; params?: Record<string, unknown> }

/** A host frame that answers like an MCP Apps host: the handshake, the create_widget
 * result it renders us for, and get_widget_data. */
function embedInHost() {
  const sent: Sent[] = []
  const host = {
    postMessage: vi.fn((message: Sent) => {
      sent.push(message)
      const reply = (data: unknown) =>
        setTimeout(() => window.dispatchEvent(new MessageEvent('message', { data, source: host as unknown as Window })))
      if (message.method === 'ui/initialize') {
        reply({ jsonrpc: '2.0', id: message.id, result: { protocolVersion: '2026-01-26', hostCapabilities: {} } })
      } else if (message.method === 'ui/notifications/initialized') {
        reply({
          jsonrpc: '2.0',
          method: 'ui/notifications/tool-result',
          params: { structuredContent: { widget: widget({ type: 'table', title: 'Coverage' }), url: '/w' } },
        })
      } else if (message.method === 'tools/call') {
        reply({ jsonrpc: '2.0', id: message.id, result: { structuredContent: coverage() } })
      }
    }),
  }
  Object.defineProperty(window, 'parent', { value: host, configurable: true })
  return sent
}

afterEach(() => {
  Object.defineProperty(window, 'parent', { value: window, configurable: true })
})

test('inside an MCP host the widget comes from the tool result and its data from a tool', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const sent = embedInHost()

  render(<WidgetRuntime>{(loaded) => <Any {...loaded} />}</WidgetRuntime>)

  expect(await screen.findByRole('table')).toBeInTheDocument()
  expect(sent.map((message) => message.method)).toEqual([
    'ui/initialize',
    'ui/notifications/initialized',
    'tools/call',
  ])
  expect(sent[2].params).toEqual({ name: 'get_widget_data', arguments: { widget_id: 'w1', limit: 1000 } })
  // No REST: the host's iframe may not share the API's origin.
  expect(fetch).not.toHaveBeenCalled()
})

test('the widget takes the theme the page names in the fragment, and follows it when it changes', () => {
  window.location.hash = '#widget=w1&theme=dark'
  const stop = followTheme()
  expect(document.documentElement.dataset.theme).toBe('dark')

  window.location.hash = '#widget=w1&theme=light'
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  expect(document.documentElement.dataset.theme).toBe('light')

  // None named: the system decides, as it does for the page.
  window.location.hash = '#widget=w1'
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  expect(document.documentElement.dataset.theme).toBeUndefined()
  stop()
  window.location.hash = ''
})

// Several inputs, and the page around the frame

test('reads several inputs in one run: without a run, the first starts it and the rest read it', async () => {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://ada.test')
    const name = url.searchParams.get('input') ?? 'main'
    if (name === 'broken') return json({ detail: 'Widget w1 has no input broken' }, 422)
    return json(coverage({ run_id: url.searchParams.get('run_id') ?? 'r-new' }))
  })
  vi.stubGlobal('fetch', fetch)

  const results = await fetchAll('w1', null, ['main', 'gap', 'broken'])
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual([
    '/api/widgets/w1/data?limit=1000',
    '/api/widgets/w1/data?limit=1000&run_id=r-new&input=gap',
    '/api/widgets/w1/data?limit=1000&run_id=r-new&input=broken',
  ])
  expect(results.get('gap')).toMatchObject({ status: 'loaded', data: { run_id: 'r-new' } })
  expect(results.get('broken')).toMatchObject({ status: 'error', message: 'Widget w1 has no input broken' })
})

test('where the page fits the frame to its content, the widget tells it its height as it changes', () => {
  const observed: (() => void)[] = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        observed.push(callback)
      }
      observe() {}
      disconnect() {}
    },
  )
  const parent = { postMessage: vi.fn() }
  Object.defineProperty(window, 'parent', { value: parent, configurable: true })
  const element = document.createElement('div')
  let height = 120.4
  element.getBoundingClientRect = () => ({ height }) as DOMRect

  // The page sizes the frame: the widget fills it and says nothing.
  window.location.hash = '#widget=w1'
  const stopFit = followFit()
  const stop = reportHeight(element)
  expect(document.documentElement.dataset.fit).toBeUndefined()
  expect(parent.postMessage).not.toHaveBeenCalled()

  window.location.hash = '#widget=w1&fit=content'
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  expect(document.documentElement.dataset.fit).toBe('content')
  expect(parent.postMessage).toHaveBeenLastCalledWith({ type: 'ada:resize', height: 121 }, '*')

  // Still loading: the page keeps the frame's usual height.
  height = 33
  element.innerHTML = '<div role="status" aria-busy="true">Loading…</div>'
  observed[0]()
  expect(parent.postMessage).toHaveBeenCalledTimes(1)
  element.innerHTML = ''

  height = 300
  observed[0]()
  observed[0]()
  expect(parent.postMessage).toHaveBeenLastCalledWith({ type: 'ada:resize', height: 300 }, '*')
  // The same height again is not news.
  expect(parent.postMessage).toHaveBeenCalledTimes(2)
  stop()
  stopFit()
  delete document.documentElement.dataset.fit
})
