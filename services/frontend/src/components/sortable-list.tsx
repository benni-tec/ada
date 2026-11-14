import {
  closestCenter,
  DndContext,
  KeyboardCode,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { CSSProperties, ReactNode } from 'react'

/** What a sortable item spreads onto its list item: the element that moves. */
export type SortItem = {
  ref: (element: HTMLElement | null) => void
  style: CSSProperties
  'data-dragging'?: true
}

/** What a sortable item spreads onto the element that moves it: its link. */
export type SortHandle = {
  ref: (element: HTMLElement | null) => void
  onPointerDown?: (event: React.PointerEvent) => void
  onKeyDown?: (event: React.KeyboardEvent) => void
  'aria-describedby'?: string
}

/** The click that ends a pointer drag lands on the dragged link. dnd-kit stops it on the
 * document, before React and the router see it, so the browser would follow the link
 * with a full page load: its default is prevented here instead. */
function swallowClick(event: MouseEvent) {
  event.preventDefault()
  document.removeEventListener('click', swallowClick, true)
}

function swallowNextClick({ activatorEvent }: DragStartEvent) {
  // A keyboard drag ends with no click.
  if (activatorEvent instanceof PointerEvent) document.addEventListener('click', swallowClick, true)
}

function stopSwallowing() {
  // dnd-kit drops its own click listener 50 ms after the drag.
  setTimeout(() => document.removeEventListener('click', swallowClick, true), 100)
}

/**
 * Items people can put in another order. Drag one with the pointer, or focus its link,
 * press Space to pick it up, move it with the arrow keys and press Space again to drop
 * it (Escape cancels). Enter still follows the link, and a click that ends a drag does
 * not. `onReorder` gets every id in the new order.
 */
export function SortableList<T extends { id: string }>({
  items,
  label,
  onReorder,
  children,
}: {
  items: readonly T[]
  label: (item: T) => string
  onReorder: (ids: string[]) => void
  children: (item: T, sort: { item: SortItem; handle: SortHandle }) => ReactNode
}) {
  const sensors = useSensors(
    // A few pixels first, so a click stays a click.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
      keyboardCodes: {
        start: [KeyboardCode.Space],
        cancel: [KeyboardCode.Esc],
        end: [KeyboardCode.Space, KeyboardCode.Enter],
      },
    }),
  )
  const name = (id: string | number) => {
    const item = items.find((candidate) => candidate.id === id)
    return item ? label(item) : 'The item'
  }
  const place = (id: string | number | undefined) => `${items.findIndex((item) => item.id === id) + 1} of ${items.length}`
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${name(active.id)}, at position ${place(active.id)}.`,
    onDragOver: ({ active, over }) => (over ? `${name(active.id)} is at position ${place(over.id)}.` : undefined),
    onDragEnd: ({ active, over }) => (over ? `${name(active.id)} was put at position ${place(over.id)}.` : undefined),
    onDragCancel: ({ active }) => `Moving ${name(active.id)} was cancelled.`,
  }

  function end({ active, over }: DragEndEvent) {
    stopSwallowing()
    if (!over || active.id === over.id) return
    const ids = items.map((item) => item.id)
    onReorder(arrayMove(ids, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))))
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      accessibility={{
        announcements,
        screenReaderInstructions: {
          draggable:
            'To move this item, press Space. Use the up and down arrow keys to move it, Space to drop it, or Escape to cancel.',
        },
      }}
      onDragStart={swallowNextClick}
      onDragEnd={end}
      onDragCancel={stopSwallowing}
    >
      <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
        {items.map((item) => (
          <Sortable key={item.id} id={item.id}>
            {(sort) => children(item, sort)}
          </Sortable>
        ))}
      </SortableContext>
    </DndContext>
  )
}

function Sortable({ id, children }: { id: string; children: (sort: { item: SortItem; handle: SortHandle }) => ReactNode }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id })
  return children({
    item: {
      ref: setNodeRef,
      style: {
        transform: CSS.Translate.toString(transform),
        transition,
        ...(isDragging ? { position: 'relative', zIndex: 10, opacity: 0.8 } : {}),
      },
      'data-dragging': isDragging || undefined,
    },
    handle: {
      ref: setActivatorNodeRef,
      // dnd-kit types its listeners as plain functions.
      onPointerDown: listeners?.onPointerDown as SortHandle['onPointerDown'],
      onKeyDown: listeners?.onKeyDown as SortHandle['onKeyDown'],
      // Only the instructions: the link stays a link, not a button.
      'aria-describedby': attributes['aria-describedby'],
    },
  })
}
