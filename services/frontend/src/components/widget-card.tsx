import { Link } from '@tanstack/react-router'
import { useContext, type ReactNode } from 'react'

import type { Widget } from '@/lib/api'
import { useLive } from '@/lib/live'
import type { CardRun } from '@/lib/view-run'
import { widgetSrc } from '@/lib/widgets'

import { PinToDashboard } from './dashboards/pin-to-dashboard'
import { PipelineAccess } from './pipeline/pipeline-access'
import { Provenance } from './provenance'
import { WidgetCardActions } from './widget-card-actions'

// Starting heights per type; the frame can be resized by dragging its lower edge.
const heights: Record<string, number> = { value: 160, table: 320, 'line-chart': 320, map: 420 }

function frameHeight(widget: Widget, tall?: boolean) {
  return (heights[widget.type] ?? 280) * (tall ? 1.75 : 1)
}

/**
 * The widget bundle in a sandboxed frame. It fetches its own data by widget id, so the
 * page only says which widget and, optionally, which run.
 *
 * `allow-same-origin` is needed for the widget's same-origin request to /api; without
 * it the frame's origin is opaque and the request becomes cross-origin.
 *
 * `reloadOnData`: whether the frame reloads when the project's data changes. Off where
 * the run is decided by the page: a page that follows the data starts a new run when it
 * changes, so the frame reloads by its new address; a report pins one run whose numbers
 * never change.
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
  return (
    <div className="resize-y overflow-hidden" style={{ height: frameHeight(widget, tall) }}>
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
 * A widget with a header saying who made it and why, and a footer of one line: its
 * pipeline at the left, actions as icons at the right. The header is the provenance of the
 * widget: in a session driven by an external agent it is the only explanation.
 *
 * `run` is the run the page shows, which the frame and the pipeline's preview both read.
 * The page starts it (one per view) and starts a new one when the data changes, which
 * reloads the frame by its new address; a frozen run never changes. So the frame neither
 * reloads on the live stream by itself nor starts a run of its own.
 */
export function WidgetCard({
  widget,
  run,
  highlighted = false,
  tall = false,
  linkToWidget = true,
  actions,
}: {
  widget: Widget
  run: CardRun
  highlighted?: boolean
  tall?: boolean
  linkToWidget?: boolean
  /** The icons at the right of the footer; by default what WidgetCardActions gives, and
   * where nothing does, "Add to dashboard". */
  actions?: ReactNode
}) {
  const fromContext = useContext(WidgetCardActions)
  const icons = actions ?? (fromContext ? fromContext(widget) : <PinToDashboard widget={widget} />)
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
      {run.id === null ? (
        <div
          className="flex animate-pulse items-center justify-center bg-neutral-50 text-sm text-neutral-500 dark:bg-neutral-950"
          style={{ height: frameHeight(widget, tall) }}
        >
          Starting the page’s run…
        </div>
      ) : (
        <WidgetFrame widget={widget} runId={run.id} tall={tall} reloadOnData={false} />
      )}
      {/* One line; an action's own rows (a chooser, an outcome) wrap below it. */}
      <footer className="flex flex-wrap items-center gap-x-2 border-t border-neutral-200 px-3 py-1 dark:border-neutral-800">
        <PipelineAccess widget={widget} run={run} />
        {icons}
      </footer>
    </article>
  )
}
