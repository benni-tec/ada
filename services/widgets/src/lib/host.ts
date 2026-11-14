// Everything a widget needs from where it runs. Widgets import only from here.
//
// Two hosts:
// - The ADA frontend (and the widgets dev server) loads a widget as /api/widget-bundles/
//   <type>.html#widget=<id>&run=<run>, on the API's origin: the widget reads REST.
// - An MCP host (MCP Apps) renders the bundle as the ui:// resource of create_widget, in
//   a sandboxed iframe with no fragment and possibly no same-origin API. There the widget
//   talks to the host over postMessage: it learns its widget from the create_widget result
//   and gets its data by calling the get_widget_data tool through the host.

import type { Widget, WidgetData } from './types'

export type WidgetContext = {
  widgetId: string
  /** The run to show; without one the server starts a new run. */
  runId: string | null
}

/** What to show, from the URL fragment: #widget=<widget id>&run=<run id>. */
export function context(): WidgetContext | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const widgetId = params.get('widget')
  return widgetId ? { widgetId, runId: params.get('run') } : null
}

/** Calls back whenever the context changes, e.g. when the page swaps the run in the
 * fragment without reloading the frame. Returns the unsubscribe function. */
export function onContextChange(listener: () => void): () => void {
  window.addEventListener('hashchange', listener)
  return () => window.removeEventListener('hashchange', listener)
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed: ${response.status}`)
  }
  return response.json()
}

/** The widget's definition: its type, title and spec. */
export function fetchWidget({ widgetId }: WidgetContext): Promise<Widget> {
  return get(`/api/widgets/${encodeURIComponent(widgetId)}`)
}

/** The output of the widget's operator, with what its columns mean (`output`) and the
 * scenario and stale flags. */
export function fetchData({ widgetId, runId }: WidgetContext, limit = 1000): Promise<WidgetData> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (runId) query.set('run_id', runId)
  return get(`/api/widgets/${encodeURIComponent(widgetId)}/data?${query}`)
}

// MCP Apps

/** Running in a frame without a fragment: the only host that does that is an MCP host. */
export function inMcpHost(): boolean {
  return context() === null && window.parent !== window
}

/** The MCP Apps protocol version this bridge speaks. */
const PROTOCOL_VERSION = '2026-01-26'
const HOST_TIMEOUT_MS = 10_000

type Message = { jsonrpc: '2.0'; id?: number; method?: string; params?: unknown; result?: unknown; error?: { message?: string } }
type ToolResult = { structuredContent?: Record<string, unknown>; isError?: boolean; content?: { type: string; text?: string }[] }

/** A JSON-RPC connection to the host frame. */
class HostBridge {
  private nextId = 1
  private readonly pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>()
  private readonly host: Window
  readonly toolResult: Promise<ToolResult>

  constructor() {
    this.host = window.parent
    let deliver: (result: ToolResult) => void = () => {}
    this.toolResult = new Promise((resolve) => (deliver = resolve))
    window.addEventListener('message', (event: MessageEvent) => {
      // Only the frame that embeds us speaks for the host.
      if (event.source !== this.host) return
      const message = event.data as Message
      if (message?.jsonrpc !== '2.0') return
      if (message.method === 'ui/notifications/tool-result') {
        deliver(message.params as ToolResult)
      } else if (message.method === undefined && message.id !== undefined) {
        const waiting = this.pending.get(message.id)
        this.pending.delete(message.id)
        if (message.error) waiting?.reject(new Error(message.error.message ?? 'The host refused the request'))
        else waiting?.resolve(message.result)
      }
    })
  }

  notify(method: string, params: unknown = {}) {
    this.host.postMessage({ jsonrpc: '2.0', method, params } satisfies Message, '*')
  }

  request<T>(method: string, params: unknown): Promise<T> {
    const id = this.nextId++
    const answer = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject })
    })
    this.host.postMessage({ jsonrpc: '2.0', id, method, params } satisfies Message, '*')
    return withTimeout(answer, `The MCP host did not answer ${method}`)
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
    return structured(await this.request<ToolResult>('tools/call', { name, arguments: args }), name)
  }
}

function withTimeout<T>(promise: Promise<T>, message: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error(message)), HOST_TIMEOUT_MS)),
  ])
}

function structured(result: ToolResult, tool: string): Record<string, unknown> {
  if (result.isError || !result.structuredContent) {
    const text = result.content?.find((part) => part.type === 'text')?.text
    throw new Error(text ?? `${tool} failed`)
  }
  return result.structuredContent
}

let bridge: Promise<HostBridge> | null = null

function connect(): Promise<HostBridge> {
  bridge ??= (async () => {
    const connection = new HostBridge()
    await connection.request('ui/initialize', {
      protocolVersion: PROTOCOL_VERSION,
      appInfo: { name: 'ada-widget', version: '0.1.0' },
      appCapabilities: {},
    })
    connection.notify('ui/notifications/initialized')
    return connection
  })()
  return bridge
}

/** In an MCP host: the widget from the create_widget result the host renders us for, and
 * its data through the get_widget_data tool. */
export async function loadFromMcpHost(limit = 1000): Promise<{ widget: Widget; data: WidgetData }> {
  const connection = await connect()
  const created = structured(await withTimeout(connection.toolResult, 'The MCP host sent no tool result'), 'create_widget')
  const widget = created.widget as Widget
  const data = await connection.callTool('get_widget_data', { widget_id: widget.id, limit })
  return { widget, data: data as WidgetData }
}
