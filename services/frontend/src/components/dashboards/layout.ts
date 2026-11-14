// The geometry of a dashboard's 12-column grid, for moving and resizing slots. Pure, so the
// rules can be tested without a pointer: what a move or a resize does, the smallest size a
// widget type makes sense at, and how the others make room.

import { GRID_COLUMNS, slotLayout, type DashboardSlot } from '@/lib/api'

export type Box = { x: number; y: number; w: number; h: number }

/** One row of the grid, and the gap between cells, in pixels. A slot's height is in rows. */
export const ROW_HEIGHT = 80
export const GAP = 16

/** The smallest a slot is useful at, in cells: a number needs little, a map or a table
 * needs room to be read. An empty slot holds only its "Add widget". */
const minimums: Record<string, { w: number; h: number }> = {
  value: { w: 2, h: 2 },
  table: { w: 3, h: 3 },
  'line-chart': { w: 3, h: 3 },
  map: { w: 3, h: 3 },
}
const fallbackMinimum = { w: 2, h: 2 }

export function minimumOf(type: string | undefined): { w: number; h: number } {
  return (type && minimums[type]) || fallbackMinimum
}

/** Maps keep their shape: stretched, a country's outline would lie about its geography. */
export function keepsAspect(type: string | undefined): boolean {
  return type === 'map'
}

/** The pixel size of a box on a grid whose columns are `column` pixels wide. */
export function pixels(box: Pick<Box, 'w' | 'h'>, column: number) {
  return { width: box.w * column + (box.w - 1) * GAP, height: box.h * ROW_HEIGHT + (box.h - 1) * GAP }
}

/** The width of one column for a grid this many pixels wide. */
export function columnWidth(gridWidth: number): number {
  return (gridWidth - GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
}

/** A box moved by whole cells, kept on the grid (x from 0, x + w at most 12, y from 0). */
export function moved(box: Box, dx: number, dy: number): Box {
  return {
    ...box,
    x: Math.min(Math.max(box.x + dx, 0), GRID_COLUMNS - box.w),
    y: Math.max(box.y + dy, 0),
  }
}

/**
 * A box resized by whole cells from its lower right corner, kept on the grid and at least
 * the type's minimum. With `aspect` (width over height, in pixels, as it was when the
 * resize began), the height follows the width, or the width the height when only that
 * changed, so the shape stays.
 */
export function resized(
  box: Box,
  dw: number,
  dh: number,
  type: string | undefined,
  aspect?: { ratio: number; column: number },
): Box {
  const min = minimumOf(type)
  const maxW = GRID_COLUMNS - box.x
  const clampW = (w: number) => Math.min(Math.max(w, min.w), maxW)
  const clampH = (h: number) => Math.max(h, min.h)
  if (!aspect) return { ...box, w: clampW(box.w + dw), h: clampH(box.h + dh) }

  const { ratio, column } = aspect
  const heightFor = (w: number) => Math.round((pixels({ w, h: 1 }, column).width / ratio + GAP) / (ROW_HEIGHT + GAP))
  const widthFor = (h: number) => Math.round((pixels({ w: 1, h }, column).height * ratio + GAP) / (column + GAP))
  if (dw !== 0) {
    const w = clampW(box.w + dw)
    return { ...box, w, h: clampH(heightFor(w)) }
  }
  if (dh === 0) return box
  const w = clampW(widthFor(clampH(box.h + dh)))
  return { ...box, w, h: clampH(heightFor(w)) }
}

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

/**
 * The slots with one of them at a new place or size; the others that it now overlaps move
 * down just far enough, and so on for those they then overlap. Nothing moves up or
 * sideways, so a layout someone made stays recognisable.
 */
export function place(slots: readonly DashboardSlot[], name: string, box: Box): DashboardSlot[] {
  const boxes = new Map(slots.map((slot) => [slot.name, slotLayout(slot)]))
  boxes.set(name, box)
  const placed: Box[] = [box]
  const others = slots
    .filter((slot) => slot.name !== name)
    .map((slot) => slot.name)
    .sort((a, b) => boxes.get(a)!.y - boxes.get(b)!.y || boxes.get(a)!.x - boxes.get(b)!.x)
  for (const other of others) {
    const current = { ...boxes.get(other)! }
    let blocker = placed.find((done) => overlaps(done, current))
    while (blocker) {
      current.y = blocker.y + blocker.h
      blocker = placed.find((done) => overlaps(done, current))
    }
    boxes.set(other, current)
    placed.push(current)
  }
  return slots.map((slot) => ({ ...slot, layout: { ...boxes.get(slot.name)! } }))
}
