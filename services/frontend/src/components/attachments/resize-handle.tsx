import { useRef, type KeyboardEvent, type PointerEvent } from 'react'

import { paneWidth } from './pane-width'

/**
 * The attachments' left edge, dragged to share the page differently (only side by side, on
 * a wide screen). It is a window splitter: focused, the arrow keys move it by a step
 * (left widens the attachments), Home and End to the bounds; its value is the attachments'
 * share of the width. A drag is remembered when it ends, a key at once.
 */
export function ResizeHandle({
  width,
  onResize,
  controls,
}: {
  width: number
  onResize: (width: number, remember: boolean) => void
  /** The id of the pane it resizes. */
  controls: string
}) {
  // The row the pane shares, measured when a drag begins.
  const drag = useRef<{ right: number; width: number } | null>(null)
  const widthAt = (event: PointerEvent<HTMLDivElement>) => {
    const row = drag.current
    return row && row.width > 0 ? ((row.right - event.clientX) / row.width) * 100 : null
  }

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const row = event.currentTarget.parentElement?.parentElement
    if (event.button !== 0 || !row) return
    event.preventDefault()
    const rect = row.getBoundingClientRect()
    drag.current = { right: rect.right, width: rect.width }
    event.currentTarget.setPointerCapture(event.pointerId)
    event.currentTarget.focus()
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const next = widthAt(event)
    if (next !== null) onResize(next, false)
  }
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const next = widthAt(event)
    drag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (next !== null) onResize(next, true)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next =
      event.key === 'ArrowLeft'
        ? width + paneWidth.step
        : event.key === 'ArrowRight'
          ? width - paneWidth.step
          : event.key === 'Home'
            ? paneWidth.min
            : event.key === 'End'
              ? paneWidth.max
              : null
    if (next === null) return
    event.preventDefault()
    onResize(next, true)
  }

  return (
    <div
      role="separator"
      aria-label="Resize the attachments"
      aria-orientation="vertical"
      aria-controls={controls}
      aria-valuenow={Math.round(width)}
      aria-valuemin={paneWidth.min}
      aria-valuemax={paneWidth.max}
      aria-valuetext={`Attachments ${Math.round(width)}% of the width`}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none outline-none lg:block"
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-transparent transition-colors group-hover:bg-ring group-focus-visible:bg-ring group-active:bg-ring"
      />
    </div>
  )
}
