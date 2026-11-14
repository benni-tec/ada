import { Link } from '@tanstack/react-router'
import { useContext, type ReactNode } from 'react'

import type { Widget } from '@/lib/api'
import { useLive } from '@/lib/live'
import { widgetSrc } from '@/lib/widgets'

import { Provenance } from './provenance'
import { WidgetCardActions } from './widget-card-actions'

// Starting heights per type; the frame can be resized by dragging its lower edge.
const heights: Record<string, number> = { value: 160, table: 320, 'line-chart': 320, map: 420 }

/**
 * The widget bundle in a sandboxed frame. It fetches its own data by widget id, so the
 * page only says which widget and, optionally, which run.
 *
 * `allow-same-origin` is needed for the widget's same-origin request to /api; without
 * it the frame's origin is opaque and the request becomes cross-origin.
 *
 * `reloadOnData`: whether the frame reloads when the project's data changes. Off where
 * the run is decided by the page: a dashboard starts a new run when data changes, so the
 * frame reloads by its new address; a report pins one run whose numbers never change.
 */
export function WidgetFrame({
  widget,
  runId,
  tall,
  reloadOnData = true,
}: {
  widget: Widget
  runId?: string | null
  tall?: boolean
  reloadOnData?: boolean
}) {
  // Changing key remounts the frame, which reloads the widget and its data.
  const { widgetEpoch } = useLive()
  const height = (heights[widget.type] ?? 280) * (tall ? 1.75 : 1)
  return (
    <div className="resize-y overflow-hidden" style={{ height }}>
      <iframe
        key={reloadOnData ? widgetEpoch : 0}
        src={widgetSrc(widget, runId)}
        title={`Widget: ${widget.title || widget.type}`}
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
        className="block h-full w-full border-0 [color-scheme:light_dark]"
      />
    </div>
  )
}

/**
 * A widget with a header saying who made it and why. The header is the provenance of
 * the widget: in a session driven by an external agent it is the only explanation.
 */
export function WidgetCard({
  widget,
  runId,
  highlighted = false,
  tall = false,
  linkToWidget = true,
  reloadOnData = true,
  actions,
}: {
  widget: Widget
  runId?: string | null
  highlighted?: boolean
  tall?: boolean
  linkToWidget?: boolean
  /** See WidgetFrame. */
  reloadOnData?: boolean
  /** Shown in a strip under the widget; defaults to what WidgetCardActions gives. */
  actions?: ReactNode
}) {
  const fromContext = useContext(WidgetCardActions)
  const strip = actions ?? fromContext?.(widget)
  const external = widget.created_by.kind === 'external_agent'
  const border = highlighted
    ? 'border-amber-400 ring-2 ring-amber-400 dark:border-amber-500 dark:ring-amber-500'
    : external
      ? 'border-violet-300 dark:border-violet-800'
      : 'border-neutral-200 dark:border-neutral-800'
  return (
    <article
      id={`widget-${widget.id}`}
      aria-label={widget.title || 'Widget'}
      data-highlighted={highlighted || undefined}
      className={`scroll-mt-20 overflow-hidden rounded-lg border bg-white dark:bg-neutral-900 ${border} ${
        external ? 'border-l-4' : ''
      }`}
    >
      <header
        className={`flex items-start justify-between gap-3 border-b px-4 py-2 ${
          external
            ? 'border-violet-200 bg-violet-50/60 dark:border-violet-900 dark:bg-violet-950/40'
            : 'border-neutral-200 dark:border-neutral-800'
        }`}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="truncate text-sm font-semibold">
            {linkToWidget ? (
              <Link
                to="/projects/$projectId/widgets/$widgetId"
                params={{ projectId: widget.project_id, widgetId: widget.id }}
                className="hover:underline focus-visible:underline"
              >
                {widget.title || 'Untitled widget'}
              </Link>
            ) : (
              widget.title || 'Untitled widget'
            )}
          </h3>
          <Provenance actor={widget.created_by} at={widget.created_at} note={widget.note} />
        </div>
        <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400">
          {widget.type}
        </span>
      </header>
      <WidgetFrame widget={widget} runId={runId} tall={tall} reloadOnData={reloadOnData} />
      {strip && <footer className="border-t border-neutral-200 px-4 py-2 dark:border-neutral-800">{strip}</footer>}
    </article>
  )
}
