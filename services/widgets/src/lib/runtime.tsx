import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'

import { context, fetchData, fetchWidget, inMcpHost, loadFromMcpHost, onContextChange, type WidgetContext } from './host'
import type { Roles, Widget, WidgetData } from './types'

import './styles.css'

/** Everything a widget type renders from. */
export type Loaded = {
  widget: Widget
  data: WidgetData
  /** What the output columns mean; empty when the operator declares none. */
  roles: Roles
}

type Result = { status: 'error'; message: string } | { status: 'loaded'; loaded: Loaded }

// The fragment as a string, so the effect below re-runs when the run in it changes.
function useFragment() {
  return useSyncExternalStore(onContextChange, () => window.location.hash)
}

/** From REST when the fragment names the widget, otherwise from the MCP host around us. */
async function load(ctx: WidgetContext | null): Promise<Loaded> {
  const [widget, data] = ctx
    ? await Promise.all([fetchWidget(ctx), fetchData(ctx)])
    : await loadFromMcpHost().then((hosted) => [hosted.widget, hosted.data] as const)
  return { widget, data, roles: data.output.roles ?? {} }
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
      <Sources sources={data.sources ?? []} />
    </div>
  )
}

/** Where the numbers came from and when they were fetched, under every widget, so no
 * number is shown without its source. */
export function Sources({ sources }: { sources: NonNullable<WidgetData['sources']> }) {
  if (sources.length === 0) return null
  return (
    <ul className="ada-sources" aria-label="Sources">
      {sources.map((source) => (
        <li key={source.operator_id}>
          {/^https?:\/\//i.test(source.address) ? (
            <a href={source.address} target="_blank" rel="noreferrer noopener" title={source.address}>
              {source.name}
            </a>
          ) : (
            <span title={source.address}>{source.name}</span>
          )}
          {' · '}
          {source.fetched_at ? `fetched ${fetched(source.fetched_at)}` : 'fetch time not recorded'}
        </li>
      ))}
    </ul>
  )
}

function fetched(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
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
