import { expect, test } from 'vitest'

import type { DashboardSlot } from '@/lib/api'

import { columnWidth, minimumOf, moved, pixels, place, resized } from './layout'

const slot = (name: string, x: number, y: number, w: number, h: number): DashboardSlot => ({
  name,
  description: '',
  widget_id: null,
  layout: { x, y, w, h },
})

test('a move stays on the grid', () => {
  expect(moved({ x: 4, y: 2, w: 6, h: 4 }, 5, -5)).toEqual({ x: 6, y: 0, w: 6, h: 4 })
  expect(moved({ x: 4, y: 2, w: 6, h: 4 }, -9, 1)).toEqual({ x: 0, y: 3, w: 6, h: 4 })
})

test('a resize keeps to the type’s minimum and the grid’s right edge', () => {
  expect(minimumOf('value')).toEqual({ w: 2, h: 2 })
  expect(minimumOf('table')).toEqual({ w: 3, h: 3 })
  expect(resized({ x: 8, y: 0, w: 4, h: 4 }, 3, -9, 'value')).toEqual({ x: 8, y: 0, w: 4, h: 2 })
  expect(resized({ x: 0, y: 0, w: 4, h: 4 }, -3, 2, 'table')).toEqual({ x: 0, y: 0, w: 3, h: 6 })
})

test('a map keeps its shape: the height follows the width, or the width the height', () => {
  const column = columnWidth(1200)
  const start = { x: 0, y: 0, w: 6, h: 4 }
  const size = pixels(start, column)
  const aspect = { ratio: size.width / size.height, column }

  const wider = resized(start, 3, 0, 'map', aspect)
  expect(wider).toEqual({ x: 0, y: 0, w: 9, h: 6 })
  // Pulled only down: it grows as a whole.
  const taller = resized(start, 0, 2, 'map', aspect)
  expect(taller.w).toBeGreaterThan(start.w)
  expect(taller.h / taller.w).toBeCloseTo(start.h / start.w, 0)
  // Pulled down and sideways at once, the width decides.
  expect(resized(start, 3, -2, 'map', aspect)).toEqual(wider)
})

test('placing a slot moves the ones in its way down, and those in theirs', () => {
  const slots = [slot('a', 0, 0, 6, 4), slot('b', 6, 0, 6, 4), slot('c', 0, 4, 12, 2)]
  const placed = place(slots, 'b', { x: 0, y: 0, w: 6, h: 4 })
  expect(placed.map((item) => [item.name, item.layout])).toEqual([
    ['a', { x: 0, y: 4, w: 6, h: 4 }],
    ['b', { x: 0, y: 0, w: 6, h: 4 }],
    ['c', { x: 0, y: 8, w: 12, h: 2 }],
  ])
  // Nothing moves up or sideways to fill a gap.
  expect(place(slots, 'c', { x: 0, y: 9, w: 12, h: 2 }).map((item) => item.layout)).toEqual([
    { x: 0, y: 0, w: 6, h: 4 },
    { x: 6, y: 0, w: 6, h: 4 },
    { x: 0, y: 9, w: 12, h: 2 },
  ])
})
