import { GripVertical, MoveDiagonal2 } from 'lucide-react'
import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'

import { Hint } from '@/components/icon-action'
import { Button } from '@/components/ui/button'
import { WidgetCard } from '@/components/widget-card'
import { WidgetCardActions } from '@/components/widget-card-actions'
import { slotLayout, type DashboardSlot, type Id, type Widget } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { CardRun } from '@/lib/view-run'

import { columnWidth, GAP, keepsAspect, moved, pixels, place, resized, ROW_HEIGHT, type Box } from './layout'
import { GoToSession } from './pin-to-dashboard'

type Widgets = Map<Id, Widget>

/** What a slot holds: the widget on the shared run, or why there is none. */
function SlotContent({
  slot,
  widgets,
  run,
  empty,
}: {
  slot: DashboardSlot
  widgets: Widgets
  run: CardRun
  empty?: (slot: DashboardSlot) => ReactNode
}) {
  const widget = slot.widget_id ? widgets.get(slot.widget_id) : undefined
  if (widget) return <WidgetCard widget={widget} run={run} fill />
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
      {slot.widget_id ? (
        <p>This slot’s widget is not available.</p>
      ) : (
        <>
          <p>
            Empty slot{slot.name ? ` “${slot.name}”` : ''}
            {slot.description ? `: ${slot.description}` : '.'}
          </p>
          {empty?.(slot)}
        </>
      )}
    </div>
  )
}

/** A widget on a dashboard is on one already: its action leads back to where it was made. */
function OnDashboard({ children }: { children: ReactNode }) {
  return <WidgetCardActions value={(widget) => <GoToSession widget={widget} />}>{children}</WidgetCardActions>
}

type Drag = {
  name: string
  mode: 'move' | 'resize'
  via: 'pointer' | 'keyboard'
  start: Box
  current: Box
  /** Where the pointer went down. */
  origin?: { x: number; y: number }
  /** For a map: width over height in pixels when the resize began, and the column width. */
  aspect?: { ratio: number; column: number }
}

const sameBox = (a: Box, b: Box) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h

/**
 * The slots on the 12-column grid, every widget reading the one run. A slot is `h` rows of
 * 80 px high and the widget fills it. Where the grid is narrower than 48rem (its own width,
 * a container query, since it may sit in half the screen beside a conversation) it is one
 * column in reading order, at the same heights.
 *
 * With `onSave`, the slots can be moved and resized: by dragging a slot's handles, or from
 * the keyboard (Enter on a handle picks the slot up, the arrow keys move or resize it,
 * Enter drops it, Escape puts it back). Others in the way move down. A drop hands the whole
 * new layout to `onChange`; saving it, as one dashboard version, is the page's business.
 */
export function DashboardGrid({
  slots,
  widgets,
  run,
  editing = false,
  onChange,
  empty,
  label = 'Dashboard widgets',
}: {
  slots: readonly DashboardSlot[]
  widgets: Widgets
  /** The dashboard's run: every widget reads it. */
  run: CardRun
  /** Show the handles to move and resize slots. */
  editing?: boolean
  /** Takes the layout after a drop. */
  onChange?: (slots: DashboardSlot[]) => void
  /** More for an empty slot, e.g. "Add widget". */
  empty?: (slot: DashboardSlot) => ReactNode
  label?: string
}) {
  const grid = useRef<HTMLUListElement>(null)
  const helpId = useId()
  const [drag, setDrag] = useState<Drag | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const base = slots
  const shown = drag ? place(base, drag.name, drag.current) : base
  const boxes = new Map(shown.map((slot) => [slot.name, slotLayout(slot)]))
  // The order in the page, and so of the keyboard, is reading order of the layout as saved:
  // not of the preview, since moving a frame in the page would reload it mid-drag.
  const ordered = [...base].sort((a, b) => {
    const [p, q] = [slotLayout(a), slotLayout(b)]
    return p.y - q.y || p.x - q.x
  })
  const typeOf = (slot: DashboardSlot) => (slot.widget_id ? widgets.get(slot.widget_id)?.type : undefined)
  const nameOf = (slot: DashboardSlot) =>
    slot.name || (slot.widget_id && widgets.get(slot.widget_id)?.title) || 'Untitled slot'

  const column = () => columnWidth(grid.current?.getBoundingClientRect().width || 1200)

  const begin = (slot: DashboardSlot, mode: Drag['mode'], via: Drag['via'], origin?: Drag['origin']) => {
    const start = slotLayout(slot)
    const width = column()
    const size = pixels(start, width)
    setDrag({
      name: slot.name,
      mode,
      via,
      start,
      current: start,
      origin,
      aspect: mode === 'resize' && keepsAspect(typeOf(slot)) ? { ratio: size.width / size.height, column: width } : undefined,
    })
  }

  const step = (current: Drag, dx: number, dy: number): Box =>
    current.mode === 'move'
      ? moved(current.start, dx, dy)
      : resized(current.start, dx, dy, typeOf(base.find((slot) => slot.name === current.name)!), current.aspect)

  const cancel = () => {
    if (drag) setAnnouncement(`${drag.name}: put back.`)
    setDrag(null)
  }

  const finish = (current: Drag) => {
    setDrag(null)
    if (!onChange || sameBox(current.start, current.current)) return
    onChange(place(base, current.name, current.current))
    setAnnouncement(`${current.name}: moved. Done saves the layout.`)
  }

  // Escape puts a dragged slot back, wherever the focus is.
  useEffect(() => {
    if (drag?.via !== 'pointer') return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setDrag(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drag?.via])

  const pointerDown = (slot: DashboardSlot, mode: Drag['mode']) => (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    try {
      // Moves keep coming to the handle when the pointer leaves it (or crosses a frame).
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // A pointer the browser does not know (a synthetic event): the drag works without.
    }
    begin(slot, mode, 'pointer', { x: event.clientX, y: event.clientY })
  }
  const pointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (drag?.via !== 'pointer' || !drag.origin) return
    const width = column()
    const dx = Math.round((event.clientX - drag.origin.x) / (width + GAP))
    const dy = Math.round((event.clientY - drag.origin.y) / (ROW_HEIGHT + GAP))
    const current = step(drag, dx, dy)
    if (!sameBox(current, drag.current)) setDrag({ ...drag, current })
  }
  const pointerUp = () => {
    if (drag?.via === 'pointer') finish(drag)
  }

  const keyDown = (slot: DashboardSlot, mode: Drag['mode']) => (event: KeyboardEvent<HTMLButtonElement>) => {
    const grabbed = drag?.via === 'keyboard' && drag.name === slot.name && drag.mode === mode ? drag : null
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (grabbed) finish(grabbed)
      else {
        begin(slot, mode, 'keyboard')
        setAnnouncement(
          `${nameOf(slot)} picked up to ${mode === 'move' ? 'move' : 'resize'}. ` +
            'Use the arrow keys, Enter to drop it, Escape to put it back.',
        )
      }
      return
    }
    if (!grabbed) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      cancel()
      return
    }
    const arrows: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    }
    const delta = arrows[event.key]
    if (!delta) return
    event.preventDefault()
    // Steps add up from the current box, so the start stays where the drag began.
    const from = { ...grabbed, start: grabbed.current }
    const current = step(from, delta[0], delta[1])
    setDrag({ ...grabbed, current })
    setAnnouncement(
      `${nameOf(slot)}: column ${current.x + 1}, row ${current.y + 1}, ${current.w} wide, ${current.h} high.`,
    )
  }

  if (slots.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
        Nothing is pinned yet. Add a widget, pin one from a session, or let an agent do it over MCP.
      </p>
    )
  }

  return (
    <OnDashboard>
      <div className="@container">
        {editing && (
          // The grid's width decides, not the window's: the agent panel narrows it too.
          <p className="mb-4 text-sm text-muted-foreground">
            <span className="@3xl:hidden">
              Too narrow to arrange: widen the window or close the agent panel to see the handles.
            </span>
            <span className="hidden @3xl:inline">
              Drag a widget by its handle to move it, or by its corner to resize it; maps keep their shape. Done
              saves all changes as one new version of the dashboard.
            </span>
          </p>
        )}
        {editing && (
          <p id={helpId} className="sr-only">
            Drag a slot by its handle, or press Enter on the handle, move it with the arrow keys and press Enter to drop
            it. Escape puts it back.
          </p>
        )}
        <ul
          ref={grid}
          aria-label={label}
          data-dragging={drag ? true : undefined}
          className="grid grid-cols-1 gap-4 @3xl:grid-cols-12 data-dragging:select-none [&[data-dragging]_iframe]:pointer-events-none"
          style={{ gridAutoRows: `${ROW_HEIGHT}px` }}
        >
          {ordered.map((slot) => {
            const { x, y, w, h } = boxes.get(slot.name)!
            const position = {
              '--col': `${x + 1} / span ${w}`,
              '--row': `${y + 1} / span ${h}`,
              '--rows': `span ${h}`,
            } as CSSProperties
            const active = drag?.name === slot.name
            const name = nameOf(slot)
            return (
              <li
                key={slot.name}
                aria-label={name}
                style={position}
                data-slot-name={slot.name}
                className={cn(
                  'relative min-w-0 [grid-row:var(--rows)] @3xl:[grid-column:var(--col)] @3xl:[grid-row:var(--row)]',
                  active && 'z-10 rounded-lg ring-2 ring-ring',
                )}
              >
                <SlotContent slot={slot} widgets={widgets} run={run} empty={empty} />
                {editing && onChange && (
                  <>
                    <Handle
                      label={`Move ${name}`}
                      hint="Move"
                      describedBy={helpId}
                      pressed={active && drag?.via === 'keyboard' && drag.mode === 'move'}
                      className="-top-2.5 -left-2.5 cursor-grab active:cursor-grabbing"
                      onPointerDown={pointerDown(slot, 'move')}
                      onPointerMove={pointerMove}
                      onPointerUp={pointerUp}
                      onPointerCancel={() => setDrag(null)}
                      onKeyDown={keyDown(slot, 'move')}
                      onBlur={() => drag?.via === 'keyboard' && drag.name === slot.name && cancel()}
                    >
                      <GripVertical />
                    </Handle>
                    <Handle
                      label={`Resize ${name}`}
                      hint={keepsAspect(typeOf(slot)) ? 'Resize (keeps its shape)' : 'Resize'}
                      describedBy={helpId}
                      pressed={active && drag?.via === 'keyboard' && drag.mode === 'resize'}
                      className="-right-2.5 -bottom-2.5 cursor-nwse-resize"
                      onPointerDown={pointerDown(slot, 'resize')}
                      onPointerMove={pointerMove}
                      onPointerUp={pointerUp}
                      onPointerCancel={() => setDrag(null)}
                      onKeyDown={keyDown(slot, 'resize')}
                      onBlur={() => drag?.via === 'keyboard' && drag.name === slot.name && cancel()}
                    >
                      <MoveDiagonal2 />
                    </Handle>
                  </>
                )}
              </li>
            )
          })}
        </ul>
        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
      </div>
    </OnDashboard>
  )
}

function Handle({
  label,
  hint,
  describedBy,
  pressed,
  className,
  children,
  ...handlers
}: {
  label: string
  hint: string
  describedBy: string
  pressed: boolean
  className: string
  children: ReactNode
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void
  onPointerMove: (event: PointerEvent<HTMLButtonElement>) => void
  onPointerUp: () => void
  onPointerCancel: () => void
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void
  onBlur: () => void
}) {
  return (
    <Hint label={hint}>
      <Button
        type="button"
        variant="secondary"
        size="icon-sm"
        aria-label={label}
        aria-describedby={describedBy}
        aria-pressed={pressed}
        // In a narrow grid there is one column: nothing to arrange, so no handles.
        className={cn('absolute z-20 hidden touch-none shadow-sm @3xl:inline-flex', className)}
        {...handlers}
      >
        {children}
      </Button>
    </Hint>
  )
}
