// Everything a widget needs from where it runs. Widgets import only from here, so running
// inside an MCP host, where data comes through tool calls instead of REST, changes this
// file and nothing else.

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
