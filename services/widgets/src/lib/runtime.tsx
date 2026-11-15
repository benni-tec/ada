import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'

import {
  canOpenPipeline,
  context,
  fetchData,
  fetchWidget,
  inMcpHost,
  loadFromMcpHost,
  onContextChange,
  openPipeline,
  readFromMcpHost,
  type WidgetContext,
} from './host'
import { MAIN_INPUT, type Roles, type Widget, type WidgetData, type WidgetSource } from './types'

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
  /** When `data` arrived. */
  fetchedAt: Date
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
  const loaded = { widget, data, roles: data.output.roles ?? {}, url, fetchedAt: new Date() }
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
  // Each answer names the sources of its own input; the footer lists them all, once each.
  // An input that did not read a source has not fixed it, so a fetch time wins.
  const sources = new Map<string, WidgetSource>()
  for (const source of Object.values(inputs).flatMap((input) => input.sources ?? [])) {
    if (!sources.get(source.operator_id)?.fetched_at) sources.set(source.operator_id, source)
  }
  return {
    ...loaded,
    data: { ...main, is_stale: stale, sources: [...sources.values()] },
    roles: main.output.roles ?? {},
    inputs,
  }
}

function onPaperChange(listener: () => void): () => void {
  const observer = new MutationObserver(listener)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-snapshot'] })
  return () => observer.disconnect()
}

/** Whether the widget is being laid out for paper: a picture of it is being taken for a
 * report's PDF (host.ts answerSnapshots). What only paper needs, e.g. a map's labels in
 * place of its tooltips, is drawn only then. */
export function usePaper(): boolean {
  return useSyncExternalStore(onPaperChange, () => 'snapshot' in document.documentElement.dataset)
}

/** Loads the widget named in the URL fragment and its data, shows loading and error
 * states, and marks stale data. Widget types render only the loaded case. */
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
      <div className="ada-widget ada-centered" role="status" aria-busy="true">
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
    <div className="ada-widget" data-stale={data.is_stale || undefined}>
      <Flags data={data} />
      <div className="ada-body">{children(result.loaded)}</div>
      <Sources sources={data.sources ?? []} stale={data.is_stale} />
    </div>
  )
}

// The sources a widget lists under itself; the pipeline, below the card, has them all.
const SHOWN_SOURCES = 2

/** Where the numbers came from and when they were fetched, under every widget, so no
 * number is shown without its source: the first two, then for the rest one line with a
 * light for how fresh all the sources are, which opens the pipeline (it lists every one),
 * or, where the frame cannot open it, the whole list. */
export function Sources({ sources, stale = false }: { sources: NonNullable<WidgetData['sources']>; stale?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  if (sources.length === 0) return null
  const hidden = sources.length - SHOWN_SOURCES
  const pipeline = canOpenPipeline()
  return (
    <>
      <SourceList sources={expanded ? sources : sources.slice(0, SHOWN_SOURCES)} />
      {hidden > 0 && !expanded && (
        <SourceSummary sources={sources} stale={stale}>
          <button
            type="button"
            aria-expanded={pipeline ? undefined : expanded}
            onClick={() => (pipeline ? openPipeline(MAIN_INPUT) : setExpanded(true))}
          >
            and {hidden} more: the Pipeline lists every source
          </button>
        </SourceSummary>
      )}
    </>
  )
}

function SourceSummary({ sources, stale, children }: { sources: WidgetSource[]; stale: boolean; children: ReactNode }) {
  const now = useNow()
  const times = sources.map((source) => (source.fetched_at ? Date.parse(source.fetched_at) : NaN))
  const missing = times.some((time) => !Number.isFinite(time))
  const oldest = Math.min(...times.filter(Number.isFinite))
  const old = now - oldest > 48 * 60 * 60 * 1000
  const status = stale ? 'red' : missing || old ? 'yellow' : 'green'
  const label = stale
    ? 'A source could not be refreshed'
    : missing
      ? 'A source has no recorded fetch time'
      : old
        ? 'A source was fetched more than 48 h ago'
        : `All ${sources.length} sources fetched within 48 h`
  return (
    <div className="ada-sources ada-sources-summary">
      <span className="ada-source-led" data-status={status} role="img" aria-label={label} title={label} />
      {children}
    </div>
  )
}

function SourceList({ sources }: { sources: WidgetSource[] }) {
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
          {source.fetched_at ? <Fetched at={source.fetched_at} /> : 'fetch time not recorded'}
        </li>
      ))}
    </ul>
  )
}

function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  return now
}

/** "fetched 14:02:11, 40 s ago" (with the date when not today), counting up while shown:
 * how live the data is, at a glance. */
function Fetched({ at }: { at: string }) {
  const now = useNow()
  const date = new Date(at)
  if (Number.isNaN(date.getTime())) return <>fetched {at}</>
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const day = date.toDateString() === new Date(now).toDateString() ? '' : `${date.toLocaleDateString(undefined, { dateStyle: 'medium' })} `
  return (
    <time dateTime={date.toISOString()} title={date.toLocaleString()}>
      fetched {day}
      {time}, {ago(now - date.getTime())}
    </time>
  )
}

function ago(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  if (seconds < 60) return `${seconds} s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours} h ago` : `${Math.floor(hours / 24)} d ago`
}

const STALE_TITLE = 'A source behind this could not be refreshed'

/** An outdated number must never look like a current one, so this marker is always
 * rendered, above the content, whatever the widget type. Bound inputs (`is_scenario`) are
 * not marked: they compose pipelines into a DAG and say nothing about the numbers. */
export function Flags({ data }: { data: Pick<WidgetData, 'is_stale'> }) {
  if (!data.is_stale) return null
  return (
    <ul className="ada-flags" aria-label="Data warnings">
      <li className="ada-flag ada-flag-stale" title={STALE_TITLE}>
        Stale: last good data, a refresh failed
      </li>
    </ul>
  )
}

/** The same marker on one value, for a widget that shows values from several inputs
 * (the text widget): the value of a stale input says so where it stands. */
export function ValueFlags({ data }: { data: Pick<WidgetData, 'is_stale'> }) {
  if (!data.is_stale) return null
  return (
    <span className="ada-flag ada-flag-inline ada-flag-stale" title={STALE_TITLE}>
      stale
    </span>
  )
}
