import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { coverage, widget } from '@/test/samples'
import { Any } from '@/widgets/any/any'

import { followTheme } from './host'
import { WidgetRuntime } from './runtime'

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
