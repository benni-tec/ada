// Turns widget data into regions with outlines, values and colour classes, independent of
// drawing, so the rules (which row, which class, what is missing) are testable without a
// layout.

import {
  columnIndex,
  firstColumn,
  formatNumber,
  formatPeriod,
  latestPerKey,
  measureFor,
  NUMERIC_TYPES,
  specText,
  suppressedAt,
  toNumber,
} from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

/** Colour classes of the sequential scale; more is darker (lighter in dark mode). */
export const CLASSES = 5
/** Projected outlines are scaled to this width or height, whichever is larger. */
const EXTENT = 1000

export type RegionState = 'value' | 'missing' | 'suppressed'

export type Region = {
  code: string
  name: string
  /** SVG path data in the map's own coordinates, empty when the row had no outline. */
  path: string
  value: number | null
  lower: number | null
  upper: number | null
  state: RegionState
  /** 0 .. CLASSES - 1 for a value, null otherwise. */
  bin: number | null
  period: string | null
}

export type Bin = { from: number; to: number }

export type MapModel = {
  value: string
  regions: Region[]
  bins: Bin[]
  /** The view box of the outlines: x, y, width, height. */
  box: [number, number, number, number]
  /** The period most regions show, for the caption; null without a time role. */
  period: string | null
  hasMissing: boolean
  hasSuppressed: boolean
}

export type MapProblem = { problem: string }

type Ring = number[][]
type Geometry = { type: 'Polygon'; coordinates: Ring[] } | { type: 'MultiPolygon'; coordinates: Ring[][] }

/**
 * Spec: `value` (default: the first measure role, else the first numeric column),
 * `geometry` (default: "geometry"), `label` (default: a column "name", else the code).
 * The region code is the geography role's column. Each region shows its latest period.
 */
export function buildMap({ widget, data, roles }: Loaded): MapModel | MapProblem {
  const spec = widget.spec
  const geo = roles.geo
  if (!geo) return { problem: 'A map needs a geography role: which column holds the region code' }
  const codeIndex = columnIndex(data, geo.code)
  if (codeIndex < 0) return { problem: `No column "${geo.code}" with the region codes in the data` }
  const geometryName = specText(spec, 'geometry') ?? 'geometry'
  const geometryIndex = columnIndex(data, geometryName)
  if (geometryIndex < 0) return { problem: `No column "${geometryName}" with the region outlines in the data` }
  const value =
    specText(spec, 'value') ?? roles.measures?.[0]?.value ?? firstColumn(data.columns, NUMERIC_TYPES)?.name
  const valueIndex = columnIndex(data, value)
  if (!value || valueIndex < 0) {
    return { problem: `No column ${value ? `"${value}"` : 'with numbers'} for the value in the data` }
  }
  const labelIndex = columnIndex(data, specText(spec, 'label') ?? 'name')

  const measure = measureFor(roles, value)
  const isSuppressed = suppressedAt(data, measure)
  const lowerIndex = columnIndex(data, measure?.lower)
  const upperIndex = columnIndex(data, measure?.upper)
  const startIndex = columnIndex(data, roles.time?.start)
  const endIndex = columnIndex(data, roles.time?.end)

  // Outlines may repeat on every row of a region; any row's will do.
  const outlines = new Map<string, Geometry>()
  for (const row of data.rows) {
    const code = String(row[codeIndex] ?? '')
    if (!outlines.has(code)) {
      const geometry = parseGeometry(row[geometryIndex])
      if (geometry) outlines.set(code, geometry)
    }
  }
  const project = projection([...outlines.values()])

  const regions: Region[] = []
  for (const [code, row] of latestPerKey(data.rows, codeIndex, endIndex)) {
    const suppressed = isSuppressed(row)
    const number = suppressed ? null : toNumber(row[valueIndex])
    const geometry = outlines.get(code)
    regions.push({
      code,
      name: labelIndex >= 0 && row[labelIndex] != null ? String(row[labelIndex]) : code,
      path: geometry ? pathOf(geometry, project.point) : '',
      value: number,
      lower: number === null ? null : toNumber(row[lowerIndex]),
      upper: number === null ? null : toNumber(row[upperIndex]),
      state: suppressed ? 'suppressed' : number === null ? 'missing' : 'value',
      bin: null,
      period: startIndex >= 0 && endIndex >= 0 ? formatPeriod(row[startIndex], row[endIndex]) : null,
    })
  }
  regions.sort((a, b) => a.name.localeCompare(b.name))

  const bins = classes(regions.flatMap((region) => (region.value === null ? [] : [region.value])))
  for (const region of regions) region.bin = region.value === null ? null : binOf(region.value, bins)

  return {
    value,
    regions,
    bins,
    box: project.box,
    period: mostCommon(regions.flatMap((region) => (region.period ? [region.period] : []))),
    hasMissing: regions.some((region) => region.state === 'missing'),
    hasSuppressed: regions.some((region) => region.state === 'suppressed'),
  }
}

/** GeoJSON Polygon or MultiPolygon, as an object or as its JSON text. */
export function parseGeometry(value: unknown): Geometry | null {
  let parsed = value
  if (typeof value === 'string') {
    try {
      parsed = JSON.parse(value)
    } catch {
      return null
    }
  }
  if (!parsed || typeof parsed !== 'object') return null
  const geometry = parsed as { type?: unknown; coordinates?: unknown }
  if ((geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') && Array.isArray(geometry.coordinates)) {
    return geometry as Geometry
  }
  return null
}

function polygons(geometry: Geometry): Ring[][] {
  return geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
}

/**
 * Longitude and latitude are drawn with the east-west distances shortened by the cosine
 * of the middle latitude, which keeps a country's shape at the scale of a widget; anything
 * else is taken as planar metres (e.g. EPSG:3067, Finland's national grid) and drawn as is.
 * Either way north is up and the result fits a box EXTENT units across.
 */
export function projection(geometries: Geometry[]) {
  const points = geometries.flatMap((geometry) => polygons(geometry).flat(2) as unknown as number[][])
  const xs = points.map((point) => point[0])
  const ys = points.map((point) => point[1])
  if (xs.length === 0) return { point: (x: number, y: number) => [x, y], box: [0, 0, 1, 1] as MapModel['box'] }
  const degrees = xs.every((x) => Math.abs(x) <= 180) && ys.every((y) => Math.abs(y) <= 90)
  const middle = (Math.min(...ys) + Math.max(...ys)) / 2
  const stretch = degrees ? Math.cos((middle * Math.PI) / 180) : 1
  const [minX, maxX] = [Math.min(...xs) * stretch, Math.max(...xs) * stretch]
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)]
  const scale = EXTENT / Math.max(maxX - minX, maxY - minY, Number.EPSILON)
  const round = (n: number) => Math.round(n * 10) / 10
  return {
    point: (x: number, y: number) => [round((x * stretch - minX) * scale), round((maxY - y) * scale)],
    box: [0, 0, round((maxX - minX) * scale), round((maxY - minY) * scale)] as MapModel['box'],
  }
}

function pathOf(geometry: Geometry, point: (x: number, y: number) => number[]): string {
  return polygons(geometry)
    .flatMap((rings) =>
      rings.map(
        (ring) =>
          ring
            .map(([x, y], index) => {
              const [px, py] = point(x, y)
              return `${index ? 'L' : 'M'}${px} ${py}`
            })
            .join('') + 'Z',
      ),
    )
    .join('')
}

/** Equal steps from the smallest to the largest value: easy to read off a legend, and
 * honest about the spread. One class when every value is the same. */
export function classes(values: number[]): Bin[] {
  if (values.length === 0) return []
  const [min, max] = [Math.min(...values), Math.max(...values)]
  if (min === max) return [{ from: min, to: max }]
  const step = (max - min) / CLASSES
  return Array.from({ length: CLASSES }, (_, i) => ({ from: min + i * step, to: i === CLASSES - 1 ? max : min + (i + 1) * step }))
}

export function binOf(value: number, bins: Bin[]): number {
  const index = bins.findIndex((bin) => value <= bin.to)
  return index < 0 ? bins.length - 1 : index
}

export function binLabel(bin: Bin): string {
  return bin.from === bin.to ? formatNumber(bin.from) : `${formatNumber(bin.from)}–${formatNumber(bin.to)}`
}

function mostCommon(values: string[]): string | null {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  let best: string | null = null
  for (const [value, count] of counts) if (best === null || count > counts.get(best)!) best = value
  return best
}
