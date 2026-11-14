// Turns a chart widget's spec and data into the Vega-Lite spec to render, and the page's
// theme into a Vega config. Pure, so it can be tested without rendering.

import { isPlainColumn } from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

type Json = Record<string, unknown>

/** Views that hold one mark (or layers of marks) can size to the frame; composed views
 * (concat, facet, repeat) size their parts themselves. */
function isSingleView(spec: Json): boolean {
  return 'mark' in spec || 'layer' in spec
}

/** The operator's rows as Vega-Lite reads them: objects keyed by column name. Dates
 * and timestamps arrive as ISO strings already. */
export function rowsAsValues({ data }: Pick<Loaded, 'data'>): Json[] {
  return data.rows.map((row) => Object.fromEntries(data.columns.map((column, i) => [column.name, row[i] ?? null])))
}

const AXIS_CHANNELS = ['x', 'y', 'x2', 'y2']
const TEXT_CHANNELS = ['text', 'tooltip']

/** A field definition naming a year column, shown as a number: write it without a
 * thousands separator (2024, not 2,024) unless the spec gives a format. */
function plainYear(definition: unknown, years: Set<string>, axis: boolean): unknown {
  if (typeof definition !== 'object' || definition === null || Array.isArray(definition)) return definition
  const def = definition as Json
  if (typeof def.field !== 'string' || !years.has(def.field)) return def
  if (def.type !== undefined && def.type !== 'quantitative') return def
  if (!axis) return 'format' in def ? def : { ...def, format: 'd' }
  if (def.axis === null) return def
  const current = (typeof def.axis === 'object' ? def.axis : {}) as Json
  return 'format' in current ? def : { ...def, axis: { ...current, format: 'd' } }
}

function withPlainYears(node: unknown, years: Set<string>): unknown {
  if (Array.isArray(node)) return node.map((item) => withPlainYears(item, years))
  if (typeof node !== 'object' || node === null) return node
  const out: Json = {}
  for (const [key, value] of Object.entries(node as Json)) {
    if (key === 'encoding' && typeof value === 'object' && value !== null && !Array.isArray(value)) {
      const encoding: Json = {}
      for (const [channel, definition] of Object.entries(value as Json)) {
        if (AXIS_CHANNELS.includes(channel)) encoding[channel] = plainYear(definition, years, true)
        else if (TEXT_CHANNELS.includes(channel))
          encoding[channel] = Array.isArray(definition)
            ? definition.map((item) => plainYear(item, years, false))
            : plainYear(definition, years, false)
        else encoding[channel] = definition
      }
      out[key] = encoding
    } else {
      out[key] = withPlainYears(value, years)
    }
  }
  return out
}

/**
 * The spec to render: the widget's Vega-Lite spec with the operator's rows as its data.
 * A single view fills the frame (`width`/`height: "container"`, autosize fit) unless the
 * spec sizes itself. Year columns are written without thousands separators.
 */
export function chartSpec({ widget, data, roles }: Loaded): Json {
  const years = new Set(data.columns.filter((column) => isPlainColumn(column, roles)).map((column) => column.name))
  const spec = withPlainYears(widget.spec, years) as Json
  const single = isSingleView(spec)
  return {
    ...spec,
    data: { values: rowsAsValues({ data }) },
    ...(single && {
      width: spec.width ?? 'container',
      height: spec.height ?? 'container',
      autosize: spec.autosize ?? { type: 'fit', contains: 'padding' },
    }),
  }
}

/** The page's palette, as styles.css defines it for the current theme. */
export type Palette = {
  text: string
  secondary: string
  muted: string
  grid: string
  series: string[]
  sequential: string[]
}

export function readPalette(root: Element = document.documentElement): Palette {
  const css = getComputedStyle(root)
  const color = (name: string) => css.getPropertyValue(name).trim()
  return {
    text: color('--text-primary'),
    secondary: color('--text-secondary'),
    muted: color('--text-muted'),
    grid: color('--grid'),
    series: Array.from({ length: 8 }, (_, i) => color(`--series-${i + 1}`)),
    sequential: Array.from({ length: 5 }, (_, i) => color(`--seq-${i + 1}`)),
  }
}

/** Drops settings whose colour is unknown (no stylesheet, as under test), so Vega keeps
 * its own default for them. */
function known(config: Json): Json {
  return Object.fromEntries(
    Object.entries(config).flatMap(([key, value]): [string, unknown][] => {
      if (value === '' || value === undefined) return []
      if (Array.isArray(value)) return value.every((item) => item !== '') ? [[key, value]] : []
      if (typeof value === 'object' && value !== null) return [[key, known(value as Json)]]
      return [[key, value]]
    }),
  )
}

/** A Vega config that matches the widget's own look: transparent background, the page's
 * text and grid colours, its categorical and sequential palettes. A spec's own `config`
 * still wins. */
export function vegaConfig(palette: Palette): Json {
  const font = getComputedStyle(document.documentElement).fontFamily || 'system-ui, sans-serif'
  const axis = {
    domainColor: palette.grid,
    gridColor: palette.grid,
    tickColor: palette.grid,
    labelColor: palette.muted,
    titleColor: palette.secondary,
    labelFont: font,
    titleFont: font,
    titleFontWeight: 500,
  }
  return known({
    background: 'transparent',
    font,
    view: { stroke: 'transparent' },
    axis,
    legend: { labelColor: palette.secondary, titleColor: palette.secondary, labelFont: font, titleFont: font },
    header: { labelColor: palette.secondary, titleColor: palette.secondary },
    title: { color: palette.text, subtitleColor: palette.secondary, font },
    mark: { color: palette.series[0] },
    text: { color: palette.text },
    // A reference line (a target) stays neutral next to the data.
    rule: { color: palette.secondary },
    range: { category: palette.series, ramp: palette.sequential, heatmap: palette.sequential },
  })
}
