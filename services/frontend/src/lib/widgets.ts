import type { Widget } from '@/lib/api'

/**
 * Where widget bundles are loaded from: VITE_WIDGETS_URL when set, else the widgets dev
 * server in development and the backend's copy of the built files in production.
 */
export const widgetsBaseUrl = (
  import.meta.env.VITE_WIDGETS_URL || (import.meta.env.DEV ? 'http://localhost:5174' : '/api/widget-bundles')
).replace(/\/+$/, '')

/** A frame's height per type before the widget says how tall it is (in reports and
 * sessions), or for good (on a widget's own page). */
export const heights: Record<string, number> = {
  value: 160,
  table: 320,
  'line-chart': 320,
  chart: 320,
  map: 420,
  text: 200,
  // Drawn by its own code, with no height of its own: a chart's, unless it posts one.
  custom: 320,
}

/** Bounds on the height a widget asks for: a frame never collapses, and a very long one
 * scrolls inside instead of taking over the page. */
export const MIN_FRAME_HEIGHT = 64
export const MAX_FRAME_HEIGHT = 2400

/** The height a frame takes for a widget's `ada:resize` message, or null for a message
 * that is not one. */
export function postedHeight(message: unknown): number | null {
  if (typeof message !== 'object' || message === null) return null
  const { type, height } = message as { type?: unknown; height?: unknown }
  if (type !== 'ada:resize' || typeof height !== 'number' || !Number.isFinite(height)) return null
  return Math.min(MAX_FRAME_HEIGHT, Math.max(MIN_FRAME_HEIGHT, Math.ceil(height)))
}

/** The input named by a widget's `ada:open-pipeline` message, or null. */
export function pipelineRequest(message: unknown): string | null {
  if (typeof message !== 'object' || message === null) return null
  const { type, input } = message as { type?: unknown; input?: unknown }
  return type === 'ada:open-pipeline' && typeof input === 'string' && input !== '' ? input : null
}

/** The address of a widget's frame: <base>/<type>.html#widget=<id>&run=<run>&theme=<…>&fit=content.
 * The run is optional; without one the widget asks the server to start one. The theme is
 * given only when the person picked one apart from the system's: inside a frame
 * `prefers-color-scheme` follows the system, not the page. It sits in the fragment, so a
 * switch changes the frame's hash without reloading it. `fit=content` asks the widget to
 * lay out at a height of its own and post it (`ada:resize`); without it the widget fills
 * its frame. */
export function widgetSrc(
  widget: Pick<Widget, 'id' | 'type'>,
  runId?: string | null,
  theme?: 'light' | 'dark',
  fitContent = false,
): string {
  const fragment = new URLSearchParams({ widget: widget.id })
  if (runId) fragment.set('run', runId)
  if (theme) fragment.set('theme', theme)
  if (fitContent) fragment.set('fit', 'content')
  return `${widgetsBaseUrl}/${encodeURIComponent(widget.type)}.html#${fragment}`
}
