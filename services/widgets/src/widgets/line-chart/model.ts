// Turns widget data into series of points, independent of drawing, so the rules (which
// columns, bands, gaps) can be tested without a layout.

import {
  columnIndex,
  firstColumn,
  formatNumber,
  measureFor,
  NUMERIC_TYPES,
  specText,
  suppressedAt,
  TIME_TYPES,
  toNumber,
} from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

/** More series than this fold into a note: categorical colours are never cycled. */
export const MAX_SERIES = 8

export type XKind = 'time' | 'number' | 'category'

export type Point = {
  x: number
  /** Null for a gap: a missing or suppressed value. */
  y: number | null
  lower: number | null
  upper: number | null
  suppressed: boolean
}

export type Series = { key: string; points: Point[] }

export type ChartModel = {
  x: string
  y: string
  xKind: XKind
  /** For a category axis, the label of each position. */
  categories: string[]
  series: Series[]
  /** Series beyond MAX_SERIES that are not drawn. */
  hiddenSeries: number
  hasBand: boolean
  hasSuppressed: boolean
}

export type ChartProblem = { problem: string }

export function buildChart({ widget, data, roles }: Loaded): ChartModel | ChartProblem {
  const spec = widget.spec
  const x =
    specText(spec, 'x') ?? roles.time?.start ?? firstColumn(data.columns, TIME_TYPES)?.name ?? data.columns[0]?.name
  const y =
    specText(spec, 'y') ?? roles.measures?.[0]?.value ?? firstColumn(data.columns, NUMERIC_TYPES, x)?.name
  const xIndex = columnIndex(data, x)
  const yIndex = columnIndex(data, y)
  if (!x || xIndex < 0) return { problem: `No column ${x ? `"${x}"` : ''} for the x axis in the data` }
  if (!y || yIndex < 0) return { problem: `No column ${y ? `"${y}"` : 'with numbers'} for the y axis in the data` }

  const seriesIndex = columnIndex(data, specText(spec, 'series'))
  const measure = measureFor(roles, y)
  const lowerIndex = columnIndex(data, measure?.lower)
  const upperIndex = columnIndex(data, measure?.upper)
  // A band only when the schema declares both bounds and the data has them; otherwise no
  // band rather than a wrong one.
  const hasBounds = lowerIndex >= 0 && upperIndex >= 0
  const isSuppressed = suppressedAt(data, measure)

  const xType = data.columns[xIndex].type
  const xKind: XKind = TIME_TYPES.has(xType) ? 'time' : NUMERIC_TYPES.has(xType) ? 'number' : 'category'
  const categories: string[] = []
  const position = (value: unknown): number | null => {
    if (value === null || value === undefined) return null
    if (xKind === 'time') {
      const time = Date.parse(String(value))
      return Number.isNaN(time) ? null : time
    }
    if (xKind === 'number') return toNumber(value)
    const label = String(value)
    const found = categories.indexOf(label)
    return found >= 0 ? found : categories.push(label) - 1
  }

  const bySeries = new Map<string, Point[]>()
  let hasSuppressed = false
  for (const row of data.rows) {
    const px = position(row[xIndex])
    if (px === null) continue
    const suppressed = isSuppressed(row)
    hasSuppressed ||= suppressed
    const key = seriesIndex >= 0 ? String(row[seriesIndex] ?? '–') : y
    const points = bySeries.get(key) ?? []
    points.push({
      x: px,
      y: suppressed ? null : toNumber(row[yIndex]),
      lower: hasBounds && !suppressed ? toNumber(row[lowerIndex]) : null,
      upper: hasBounds && !suppressed ? toNumber(row[upperIndex]) : null,
      suppressed,
    })
    bySeries.set(key, points)
  }

  const all = [...bySeries].map(([key, points]) => ({ key, points: points.sort((a, b) => a.x - b.x) }))
  const series = all.slice(0, MAX_SERIES)
  return {
    x,
    y,
    xKind,
    categories,
    series,
    hiddenSeries: all.length - series.length,
    hasBand: series.some((s) => s.points.some((p) => p.lower !== null && p.upper !== null)),
    hasSuppressed,
  }
}

/** Splits points into runs that can be drawn as one line: a gap ends a run. */
export function runs(points: Point[], keep: (point: Point) => boolean = (point) => point.y !== null): Point[][] {
  const result: Point[][] = []
  let current: Point[] = []
  for (const point of points) {
    if (keep(point)) {
      current.push(point)
    } else if (current.length > 0) {
      result.push(current)
      current = []
    }
  }
  if (current.length > 0) result.push(current)
  return result
}

/** Round tick values covering [min, max], about `count` of them. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (min === max) {
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.1 : 1
    return niceTicks(min - pad, max + pad, count)
  }
  const raw = (max - min) / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const fraction = raw / magnitude
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude
  const first = Math.floor(min / step)
  const last = Math.ceil(max / step)
  // Multiplying instead of adding up steps avoids drift (0.30000000000000004).
  return Array.from({ length: last - first + 1 }, (_, i) => Number(((first + i) * step).toPrecision(12)))
}

/** The label of an x position, as the axis and the tooltip show it. */
export function xLabel(model: Pick<ChartModel, 'xKind' | 'categories'>, x: number, yearsOnly: boolean): string {
  if (model.xKind === 'category') return model.categories[x] ?? ''
  if (model.xKind === 'number') return formatNumber(x)
  const iso = new Date(x).toISOString()
  return yearsOnly ? iso.slice(0, 4) : iso.slice(0, 10)
}

/** True when every time is the first of January, so years label the axis best. */
export function allYearStarts(xs: number[]): boolean {
  return xs.every((x) => new Date(x).toISOString().slice(5, 10) === '01-01')
}
