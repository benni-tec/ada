import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { coverage, widget } from '@/test/samples'
import { Any } from '@/widgets/any/any'

import { followTheme } from './host'
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
})

test('marks simulated and stale data', async () => {
  serve({ data: coverage({ is_scenario: true, is_stale: true }) })
  show()

  expect(await screen.findByText('6 rows, 1 measures')).toBeInTheDocument()
  const flags = screen.getByRole('list', { name: 'Data warnings' })
  expect(within(flags).getAllByRole('listitem').map((flag) => flag.textContent)).toEqual([
    expect.stringContaining('Scenario: simulated numbers'),
    expect.stringContaining('Stale'),
  ])
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
