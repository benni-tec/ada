import { useContext, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import type { Widget } from '@/lib/api'
import { useLive } from '@/lib/live'
import { cn } from '@/lib/utils'
import type { CardRun } from '@/lib/view-run'
import { widgetSrc } from '@/lib/widgets'

import { PinToDashboard } from './dashboards/pin-to-dashboard'
import { OpenWidgetLink } from './open-widget-link'
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
 *
 * `fill`: as tall as its container (a dashboard cell, the full-size modal) instead of a
 * height of its own.
 */
export function WidgetFrame({
  widget,
  runId,
  tall,
  fill = false,
  reloadOnData = true,
}: {
  widget: Widget
  runId?: string | null
  tall?: boolean
  fill?: boolean
  reloadOnData?: boolean
}) {
  // Changing key remounts the frame, which reloads the widget and its data.
  const { widgetEpoch } = useLive()
  return (
    <div
      className={fill ? 'min-h-0 flex-1 overflow-hidden' : 'resize-y overflow-hidden'}
      style={fill ? undefined : { height: frameHeight(widget, tall) }}
    >
      <iframe
        key={reloadOnData ? widgetEpoch : 0}
        src={widgetSrc(widget, runId)}
        title={`Widget: ${widget.title || widget.type}`}
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
        // The frame inherits the page's colour scheme (index.css), so it follows the theme.
        className="block h-full w-full border-0"
      />
    </div>
  )
}

/**
 * A widget with a header saying who made it and why, and a footer of one line: "Pipeline"
 * at the left, actions as icons at the right. The header is the provenance of the widget:
 * in a session driven by an external agent it is the only explanation.
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
  fill = false,
  openable = true,
  actions,
  className,
}: {
  widget: Widget
  run: CardRun
  highlighted?: boolean
  tall?: boolean
  /** As tall as its container, the frame taking what header and footer leave. */
  fill?: boolean
  /** Offers to open it full size over the page (not inside that modal itself). */
  openable?: boolean
  /** The icons at the right of the footer; by default what WidgetCardActions gives, and
   * where nothing does, "Add to dashboard". */
  actions?: ReactNode
  className?: string
}) {
  const fromContext = useContext(WidgetCardActions)
  const icons = actions ?? (fromContext ? fromContext(widget) : <PinToDashboard widget={widget} />)
  const external = widget.created_by.kind === 'external_agent'
  const border = highlighted
    ? 'border-amber-400 ring-2 ring-amber-400 dark:border-amber-500 dark:ring-amber-500'
    : external
      ? 'border-violet-300 dark:border-violet-800'
      : 'border-border'
  return (
    <article
      id={`widget-${widget.id}`}
      aria-label={widget.title || 'Widget'}
      data-highlighted={highlighted || undefined}
      className={cn(
        'scroll-mt-20 overflow-hidden rounded-lg border bg-card text-card-foreground',
        border,
        external && 'border-l-4',
        fill && 'flex h-full min-h-0 flex-col',
        className,
      )}
    >
      <header
        className={cn(
          'flex shrink-0 items-start justify-between gap-3 border-b px-4 py-2',
          external && 'border-violet-200 bg-violet-50/60 dark:border-violet-900 dark:bg-violet-950/40',
        )}
      >
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="truncate text-sm font-semibold">{widget.title || 'Untitled widget'}</h3>
          <Provenance actor={widget.created_by} at={widget.created_at} note={widget.note} />
        </div>
        <Badge variant="secondary" className="shrink-0 font-mono">
          {widget.type}
        </Badge>
      </header>
      {run.id === null ? (
        <div
          className={cn(
            'flex animate-pulse items-center justify-center bg-muted/50 text-sm text-muted-foreground',
            fill && 'min-h-0 flex-1',
          )}
          style={fill ? undefined : { height: frameHeight(widget, tall) }}
        >
          Starting the page’s run…
        </div>
      ) : (
        <WidgetFrame widget={widget} runId={run.id} tall={tall} fill={fill} reloadOnData={false} />
      )}
      {/* One line; an action's own rows (a chooser, an outcome) wrap below it. */}
      <footer className="flex shrink-0 flex-wrap items-center gap-x-1 border-t px-2 py-1">
        <PipelineAccess widget={widget} run={run} />
        {openable && <OpenWidgetLink widget={widget} run={run} />}
        {icons}
      </footer>
    </article>
  )
}
