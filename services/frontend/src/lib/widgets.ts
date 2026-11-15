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

/** A picture of a widget: a PNG data URL, at twice the size in CSS pixels it was drawn at. */
export type WidgetSnapshot = { image: string; width: number; height: number }

/**
 * Draws a widget in a frame of its own, unseen, light and as tall as its content, at
 * a run, and asks it for a picture (`ada:snapshot`, answered once it is drawn): what a
 * report's PDF shows. The frames on the page cannot be used: they load lazily and follow
 * the page's theme. The request is repeated until answered, as the widget may not listen
 * yet when its frame has loaded.
 */
export function snapshotWidget(
  widget: Pick<Widget, 'id' | 'type'>,
  runId: string,
  { width = 720, timeoutMs = 45_000 }: { width?: number; timeoutMs?: number } = {},
): Promise<WidgetSnapshot> {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID()
    const frame = document.createElement('iframe')
    frame.src = widgetSrc(widget, runId, 'light', true)
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin')
    frame.setAttribute('aria-hidden', 'true')
    frame.tabIndex = -1
    // In the window but unseen and behind everything: a frame outside it is not drawn.
    Object.assign(frame.style, {
      position: 'fixed',
      left: '0',
      top: '0',
      width: `${width}px`,
      height: `${MAX_FRAME_HEIGHT}px`,
      border: '0',
      opacity: '0',
      pointerEvents: 'none',
      zIndex: '-1',
    })
    const ask = () => frame.contentWindow?.postMessage({ type: 'ada:snapshot', id }, '*')
    let asking: ReturnType<typeof setInterval> | undefined
    const done = () => {
      clearInterval(asking)
      clearTimeout(timer)
      window.removeEventListener('message', listen)
      frame.remove()
    }
    const timer = setTimeout(() => {
      done()
      reject(new Error('The widget did not draw in time'))
    }, timeoutMs)
    const listen = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow) return
      const answer = snapshotAnswer(event.data, id)
      if (!answer) return
      done()
      if ('error' in answer) reject(new Error(answer.error))
      else resolve(answer)
    }
    window.addEventListener('message', listen)
    frame.addEventListener('load', () => {
      ask()
      asking = setInterval(ask, 3000)
    })
    document.body.append(frame)
  })
}

/** A widget's answer to the snapshot request `id`, or null for any other message. */
export function snapshotAnswer(message: unknown, id: string): WidgetSnapshot | { error: string } | null {
  if (typeof message !== 'object' || message === null) return null
  const answer = message as { type?: unknown; id?: unknown; image?: unknown; width?: unknown; height?: unknown; error?: unknown }
  if (answer.type !== 'ada:snapshot' || answer.id !== id) return null
  if (typeof answer.error === 'string') return { error: answer.error }
  if (typeof answer.image !== 'string' || typeof answer.width !== 'number' || typeof answer.height !== 'number') return null
  return { image: answer.image, width: answer.width, height: answer.height }
}
