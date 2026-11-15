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
  /** Where its label goes, inside its largest part; null without an outline. */
  anchor: [number, number] | null
  /** The area of its largest part, in the map's own units: big regions are labelled first. */
  area: number
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
      ...(geometry ? anchorOf(geometry, project.point) : { anchor: null, area: 0 }),
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

/**
 * A point to label a region at: the centroid of its largest part, or, when that falls
 * outside the part (a crescent) or in one of its holes, the middle of the widest stretch
 * of the part along the centroid's line. With the area of that part's outline.
 */
export function anchorOf(
  geometry: Geometry,
  point: (x: number, y: number) => number[],
): { anchor: [number, number] | null; area: number } {
  let best: { rings: number[][][]; area: number; x: number; y: number } | null = null
  for (const polygon of polygons(geometry)) {
    const rings = polygon.map((ring) => ring.map(([x, y]) => point(x, y)))
    const ring = rings[0] ?? []
    let twice = 0
    let cx = 0
    let cy = 0
    for (let i = 0; i < ring.length; i++) {
      const [x0, y0] = ring[i]
      const [x1, y1] = ring[(i + 1) % ring.length]
      const cross = x0 * y1 - x1 * y0
      twice += cross
      cx += (x0 + x1) * cross
      cy += (y0 + y1) * cross
    }
    const area = Math.abs(twice / 2)
    if (twice !== 0 && (!best || area > best.area)) best = { rings, area, x: cx / (3 * twice), y: cy / (3 * twice) }
  }
  if (!best) return { anchor: null, area: 0 }
  if (inside(best.rings, best.x, best.y)) return { anchor: [best.x, best.y], area: best.area }
  // Where the centroid's horizontal line crosses the outline and any hole, inside runs
  // between pairs.
  const { rings, y } = best
  const crossings = rings
    .flatMap((ring) =>
      ring.flatMap(([x0, y0], i) => {
        const [x1, y1] = ring[(i + 1) % ring.length]
        return (y0 > y) !== (y1 > y) ? [x0 + ((y - y0) * (x1 - x0)) / (y1 - y0)] : []
      }),
    )
    .sort((a, b) => a - b)
  let widest: [number, number] = [crossings[0] ?? best.x, crossings[1] ?? best.x]
  for (let i = 0; i + 1 < crossings.length; i += 2)
    if (crossings[i + 1] - crossings[i] > widest[1] - widest[0]) widest = [crossings[i], crossings[i + 1]]
  return { anchor: [(widest[0] + widest[1]) / 2, y], area: best.area }
}

/** Inside a polygon: within its outline and out of its holes (even-odd over every ring). */
function inside(rings: number[][][], x: number, y: number): boolean {
  let within = false
  for (const ring of rings)
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i]
      const [xj, yj] = ring[j]
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) within = !within
    }
  return within
}

/** Region names without the words most of them end with ("… wellbeing services county"),
 * which say nothing on a map of such regions. */
export function shortNames(names: string[]): string[] {
  const words = names.map((name) => name.split(/\s+/))
  for (let take = 4; take >= 2; take--) {
    const counts = new Map<string, number>()
    for (const w of words) if (w.length > take) counts.set(w.slice(-take).join(' '), (counts.get(w.slice(-take).join(' ')) ?? 0) + 1)
    const [suffix, count] = [...counts].sort((a, b) => b[1] - a[1])[0] ?? ['', 0]
    if (count >= Math.max(2, names.length / 2))
      return words.map((w) => (w.length > take && w.slice(-take).join(' ') === suffix ? w.slice(0, -take).join(' ') : w.join(' ')))
  }
  return names
}

/** A label on the map: the region's short name and value, or, where that does not fit,
 * a number that the key under the map explains. */
export type Label =
  | { code: string; x: number; y: number; lines: string[] }
  /** A number at (x, y); when moved off its region to stay clear, a line leads to `from`. */
  | { code: string; x: number; y: number; number: number; from?: [number, number] }

/**
 * Labels for the regions, biggest first: a name and value at the region's anchor, or just
 * above, below or beside it, where it stays within `bounds` (x0, y0, x1, y1: what the map
 * shows), overlaps no label already placed and covers no other region's anchor (where that
 * region's number may go); else a number. Sizes are in the map's own units, so the labels
 * scale with the map. `size` is the text size.
 */
export function placeLabels(
  regions: Region[],
  texts: Map<string, string[]>,
  size: number,
  bounds: [number, number, number, number],
): Label[] {
  type Box = [number, number, number, number]
  const anchored = regions.filter((r) => r.anchor)
  const taken: Box[] = []
  const within = (box: Box) => box[0] >= bounds[0] && box[1] >= bounds[1] && box[2] <= bounds[2] && box[3] <= bounds[3]
  const free = (box: Box, code: string) =>
    within(box) &&
    taken.every(([x0, y0, x1, y1]) => box[2] < x0 || box[0] > x1 || box[3] < y0 || box[1] > y1) &&
    anchored.every(
      (r) => r.code === code || r.anchor![0] < box[0] - size || r.anchor![0] > box[2] + size || r.anchor![1] < box[1] - size || r.anchor![1] > box[3] + size,
    )
  const labels: Label[] = []
  const numbered: Region[] = []
  for (const region of [...anchored].sort((a, b) => b.area - a.area)) {
    const [ax, ay] = region.anchor!
    const lines = texts.get(region.code) ?? [region.name]
    const width = Math.max(...lines.map((line) => line.length)) * size * 0.55
    const height = lines.length * size * 1.15
    const shifts = [[0, 0], [0, -height * 0.6], [0, height * 0.6], [-width * 0.3, 0], [width * 0.3, 0]]
    const spot = shifts
      .map(([dx, dy]): [number, number, Box] => [ax + dx, ay + dy, [ax + dx - width / 2, ay + dy - height / 2, ax + dx + width / 2, ay + dy + height / 2]])
      .find(([, , box]) => free(box, region.code))
    if (spot) {
      taken.push(spot[2])
      labels.push({ code: region.code, x: spot[0], y: spot[1], lines })
    } else numbered.push(region)
  }
  // Numbered north to south, then west to east, so the key reads down the map.
  numbered.sort((a, b) => a.anchor![1] - b.anchor![1] || a.anchor![0] - b.anchor![0])
  // A number overlapping another moves out on rings around its anchor, south (the sea,
  // on most maps of regions) first, ring after ring until it is clear.
  const radius = size * 0.62
  const markers: [number, number][] = []
  const clearOf = (x: number, y: number) =>
    x - radius >= bounds[0] &&
    y - radius >= bounds[1] &&
    x + radius <= bounds[2] &&
    y + radius <= bounds[3] &&
    markers.every(([mx, my]) => Math.hypot(mx - x, my - y) > radius * 2.2) &&
    taken.every(([x0, y0, x1, y1]) => x < x0 - radius || x > x1 + radius || y < y0 - radius || y > y1 + radius)
  const farthest = Math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1])
  numbered.forEach((region, index) => {
    const [ax, ay] = region.anchor!
    let spot: [number, number] | undefined = clearOf(ax, ay) ? [ax, ay] : undefined
    for (let step = 2.6; !spot && radius * step < farthest; step += 1.6) {
      const around = [90, 135, 45, 180, 0, 225, 315, 270].map((degrees): [number, number] => [
        ax + Math.cos((degrees * Math.PI) / 180) * radius * step,
        ay + Math.sin((degrees * Math.PI) / 180) * radius * step,
      ])
      spot = around.find(([x, y]) => clearOf(x, y))
    }
    spot ??= [ax, ay]
    markers.push(spot)
    const moved = spot[0] !== ax || spot[1] !== ay
    labels.push({ code: region.code, x: spot[0], y: spot[1], number: index + 1, ...(moved ? { from: [ax, ay] as [number, number] } : {}) })
  })
  return labels
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
