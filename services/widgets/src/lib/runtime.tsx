import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'

import {
  context,
  fetchData,
  fetchWidget,
  inMcpHost,
  loadFromMcpHost,
  onContextChange,
  readFromMcpHost,
  type WidgetContext,
} from './host'
import { MAIN_INPUT, type Roles, type Widget, type WidgetData } from './types'

import './styles.css'

/** Everything a widget type renders from. */
export type Loaded = {
  widget: Widget
  data: WidgetData
  /** What the output columns mean; empty when the operator declares none. */
  roles: Roles
  /** Every input by name, "main" (`data`) included, all in `data`'s run. Only the types
   * that read further inputs get them (custom). */
  inputs?: Record<string, WidgetData>
  /** The widget's address in ADA, when an MCP host gave it (create_widget's `url`). */
  url?: string
}

type Result = { status: 'error'; message: string } | { status: 'loaded'; loaded: Loaded }

/** Rows a custom widget reads of each input. */
const CUSTOM_ROWS = 5000

// The fragment as a string, so the effect below re-runs when the run in it changes.
function useFragment() {
  return useSyncExternalStore(onContextChange, () => window.location.hash)
}

/** From REST when the fragment names the widget, otherwise from the MCP host around us. */
async function load(ctx: WidgetContext | null): Promise<Loaded> {
  const { widget, data, url } = ctx
    ? await Promise.all([fetchWidget(ctx), fetchData(ctx)]).then(([widget, data]) => ({ widget, data, url: undefined }))
    : await loadFromMcpHost()
  const loaded = { widget, data, roles: data.output.roles ?? {}, url }
  return widget.type === 'custom' ? withInputs(loaded, ctx) : loaded
}

/**
 * A custom widget reads every input, up to 5,000 rows each, in the run of the first
 * answer; "main" again only when the first answer was cut short. The data counts as stale
 * when any input is.
 */
async function withInputs(loaded: Loaded, ctx: WidgetContext | null): Promise<Loaded> {
  const { widget, data } = loaded
  const read = (input?: string) =>
    ctx
      ? fetchData({ ...ctx, runId: data.run_id }, CUSTOM_ROWS, input)
      : readFromMcpHost(widget.id, data.run_id, CUSTOM_ROWS, input)
  const names = Object.keys(widget.inputs ?? {}).filter((name) => name !== MAIN_INPUT)
  const [main, ...others] = await Promise.all([data.truncated ? read() : data, ...names.map(read)])
  const inputs: Record<string, WidgetData> = {
    [MAIN_INPUT]: main,
    ...Object.fromEntries(names.map((name, i) => [name, others[i]] as const)),
  }
  const stale = Object.values(inputs).some((input) => input.is_stale)
  return { ...loaded, data: { ...main, is_stale: stale }, roles: main.output.roles ?? {}, inputs }
}

/** Loads the widget named in the URL fragment and its data, shows loading and error
 * states, and marks scenario and stale data. Widget types render only the loaded case. */
export function WidgetRuntime({ children }: { children: (loaded: Loaded) => ReactNode }) {
  const fragment = useFragment()
  const ctx = context()
  const hosted = !ctx && inMcpHost()
  // Remembers which fragment a result belongs to: a result for an older fragment means
  // the new one is still loading.
  const [state, setState] = useState<{ fragment: string; result: Result } | null>(null)

  useEffect(() => {
    const ctx = context()
    if (!ctx && !inMcpHost()) return
    let current = true
    load(ctx).then(
      (loaded) => current && setState({ fragment, result: { status: 'loaded', loaded } }),
      (error: unknown) =>
        current &&
        setState({
          fragment,
          result: { status: 'error', message: error instanceof Error ? error.message : String(error) },
        }),
    )
    return () => {
      current = false
    }
  }, [fragment])

  const result: Result | null = !ctx && !hosted
    ? { status: 'error', message: 'No widget to show: the address names no widget.' }
    : state?.fragment === fragment
      ? state.result
      : null

  if (!result) {
    return (
      <div className="ada-widget ada-centered" role="status">
        <span className="ada-muted">Loading…</span>
      </div>
    )
  }
  if (result.status === 'error') {
    return (
      <div className="ada-widget ada-centered">
        <p role="alert" className="ada-error">
          {result.message}
        </p>
      </div>
    )
  }
  const { data } = result.loaded
  return (
    <div className="ada-widget" data-scenario={data.is_scenario || undefined} data-stale={data.is_stale || undefined}>
      <Flags data={data} />
      <div className="ada-body">{children(result.loaded)}</div>
    </div>
  )
}

/** A simulated or outdated number must never look like a measured, current one, so these
 * markers are always rendered, above the content, whatever the widget type. */
export function Flags({ data }: { data: Pick<WidgetData, 'is_scenario' | 'is_stale'> }) {
  if (!data.is_scenario && !data.is_stale) return null
  return (
    <ul className="ada-flags" aria-label="Data warnings">
      {data.is_scenario && (
        <li className="ada-flag ada-flag-scenario" title="This run binds inputs to other pipelines">
          Scenario: simulated numbers
        </li>
      )}
      {data.is_stale && (
        <li className="ada-flag ada-flag-stale" title="A source behind this could not be refreshed">
          Stale: last good data, a refresh failed
        </li>
      )}
    </ul>
  )
}
