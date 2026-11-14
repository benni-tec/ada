import type { Widget } from '@/lib/api'

/**
 * Where widget bundles are loaded from: VITE_WIDGETS_URL when set, else the widgets dev
 * server in development and the backend's copy of the built files in production.
 */
export const widgetsBaseUrl = (
  import.meta.env.VITE_WIDGETS_URL || (import.meta.env.DEV ? 'http://localhost:5174' : '/api/widget-bundles')
).replace(/\/+$/, '')

/** The address of a widget's frame: <base>/<type>.html#widget=<id>&run=<run>&theme=<…>.
 * The run is optional; without one the widget asks the server to start one. The theme is
 * given only when the person picked one apart from the system's: inside a frame
 * `prefers-color-scheme` follows the system, not the page. It sits in the fragment, so a
 * switch changes the frame's hash without reloading it. */
export function widgetSrc(
  widget: Pick<Widget, 'id' | 'type'>,
  runId?: string | null,
  theme?: 'light' | 'dark',
): string {
  const fragment = new URLSearchParams({ widget: widget.id })
  if (runId) fragment.set('run', runId)
  if (theme) fragment.set('theme', theme)
  return `${widgetsBaseUrl}/${encodeURIComponent(widget.type)}.html#${fragment}`
}
