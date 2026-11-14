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

/**
 * Light or dark as the page that frames the widget says (`#…&theme=light|dark`), when the
 * person picked one there: inside a frame `prefers-color-scheme` follows the system, not
 * the page. Without the parameter the widget follows the system, as the page then does.
 * Applied now and whenever the fragment changes, so a theme switch needs no reload.
 */
export function followTheme(): () => void {
  const apply = () => {
    const theme = new URLSearchParams(window.location.hash.slice(1)).get('theme')
    const root = document.documentElement
    if (theme === 'light' || theme === 'dark') root.dataset.theme = theme
    else delete root.dataset.theme
  }
  apply()
  window.addEventListener('hashchange', apply)
  return () => window.removeEventListener('hashchange', apply)
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

/** The input every widget has: its own operator. */
export const MAIN_INPUT = 'main'

/** The output of one of the widget's inputs (by default its own operator, "main"), with
 * what its columns mean (`output`) and the scenario and stale flags. */
export function fetchData({ widgetId, runId }: WidgetContext, limit = 1000, input = MAIN_INPUT): Promise<WidgetData> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (runId) query.set('run_id', runId)
  if (input !== MAIN_INPUT) query.set('input', input)
  return get(`/api/widgets/${encodeURIComponent(widgetId)}/data?${query}`)
}

/** One input as a view read it, or why it could not be read. */
export type InputResult =
  | { input: string; status: 'loaded'; data: WidgetData; fetchedAt: Date }
  | { input: string; status: 'error'; message: string }

/** One input, from REST, or in an MCP host through its get_widget_data tool. */
async function readInput(widgetId: string, runId: string | null, input: string, limit: number): Promise<WidgetData> {
  if (!inMcpHost()) return fetchData({ widgetId, runId }, limit, input)
  const connection = await connect()
  const args: Record<string, unknown> = { widget_id: widgetId, limit, input }
  if (runId) args.run_id = runId
  return (await connection.callTool('get_widget_data', args)) as WidgetData
}

async function settle(widgetId: string, runId: string | null, input: string, limit: number): Promise<InputResult> {
  try {
    const data = await readInput(widgetId, runId, input, limit)
    return { input, status: 'loaded', data, fetchedAt: new Date() }
  } catch (error) {
    return { input, status: 'error', message: error instanceof Error ? error.message : String(error) }
  }
}

/**
 * Several inputs of one widget, all in one run, as one view must show them. With a run
 * they are read side by side; without one the first input is read first, which starts the
 * run, and the rest read that run. Each input fails on its own; when the first fails
 * without a run, so do the rest, since there is no run to read them in.
 */
export async function fetchAll(
  widgetId: string,
  runId: string | null,
  inputs: readonly string[],
  limit = 1000,
): Promise<Map<string, InputResult>> {
  const names = [...new Set(inputs)]
  const results = new Map<string, InputResult>()
  let run = runId
  if (!run && names.length > 0) {
    const first = await settle(widgetId, null, names[0], limit)
    results.set(first.input, first)
    if (first.status === 'error') {
      for (const input of names.slice(1)) results.set(input, { input, status: 'error', message: first.message })
      return results
    }
    run = first.data.run_id
  }
  const rest = await Promise.all(names.filter((name) => !results.has(name)).map((name) => settle(widgetId, run, name, limit)))
  for (const result of rest) results.set(result.input, result)
  return results
}

/**
 * How the page sizes the frame (`#…&fit=content`): to the widget's content, or (without
 * the parameter) the page decides and the widget fills what it is given. Set on the root
 * as `data-fit`, which styles.css reads: in content mode every type lays out at a height
 * of its own instead of filling the frame.
 */
export function fitsContent(): boolean {
  return new URLSearchParams(window.location.hash.slice(1)).get('fit') === 'content'
}

export function followFit(): () => void {
  const apply = () => {
    const root = document.documentElement
    if (fitsContent()) root.dataset.fit = 'content'
    else delete root.dataset.fit
  }
  apply()
  window.addEventListener('hashchange', apply)
  return () => window.removeEventListener('hashchange', apply)
}

/** Messages to the ADA page that frames the widget. The page checks they come from its
 * own frame; they carry nothing secret, so any origin may read them. */
export type PageMessage =
  | { type: 'ada:resize'; height: number }
  | { type: 'ada:open-pipeline'; input: string }

/** Framed by an ADA page, which listens for PageMessages (an MCP host does not). */
function framedByPage(): boolean {
  return context() !== null && window.parent !== window
}

function tellPage(message: PageMessage) {
  if (framedByPage()) window.parent.postMessage(message, '*')
}

/** Whether a click can open an input's pipeline: only an ADA page has the dialog. */
export function canOpenPipeline(): boolean {
  return framedByPage()
}

/** Asks the page to open the pipeline of one of the widget's inputs. */
export function openPipeline(input: string) {
  tellPage({ type: 'ada:open-pipeline', input })
}

/**
 * In content mode, tells the page the height of the element (the widget's root) now and
 * whenever it changes, so the page can size the frame to it. Nothing in fill mode, where
 * the page sizes the frame. Returns the function that stops it.
 */
export function reportHeight(element: HTMLElement): () => void {
  if (!framedByPage() || typeof ResizeObserver === 'undefined') return () => {}
  let last = -1
  const post = () => {
    if (!fitsContent()) return
    const height = Math.ceil(element.getBoundingClientRect().height)
    if (height === last) return
    last = height
    tellPage({ type: 'ada:resize', height })
  }
  const observer = new ResizeObserver(post)
  observer.observe(element)
  post()
  // Switching to content mode by the fragment posts at once.
  const onHash = () => {
    last = -1
    post()
  }
  window.addEventListener('hashchange', onHash)
  return () => {
    observer.disconnect()
    window.removeEventListener('hashchange', onHash)
  }
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
