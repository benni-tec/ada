// Everything a widget needs from where it runs. Widgets import only from here, so running
// inside an MCP host, where data comes through tool calls instead of REST, changes this
// file and nothing else.

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

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Request failed: ${response.status}`)
  }
  return response.json()
}

/** The widget's definition: its type, title and spec. */
export function fetchWidget<T>({ widgetId }: WidgetContext): Promise<T> {
  return get(`/api/widgets/${widgetId}`)
}

/** The output of the widget's operator, with the scenario and stale flags. */
export function fetchData<T>({ widgetId, runId }: WidgetContext, limit = 1000): Promise<T> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (runId) query.set('run_id', runId)
  return get(`/api/widgets/${widgetId}/data?${query}`)
}
