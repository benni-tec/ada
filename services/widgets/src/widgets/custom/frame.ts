// What the custom widget's frame gives the sandboxed frame that runs the code: a document
// that can load nothing, the data as the code reads it, and the page's colours.

import type { Loaded } from '@/lib/runtime'
import type { WidgetData } from '@/lib/types'
import { rowsAsValues } from '@/widgets/chart/spec'

import childScript from './child-main.ts?script'
import d3Script from './libraries/d3.ts?script'
import vegaScript from './libraries/vega.ts?script'
import type { Colors, Data, Dataset } from './protocol'

const LIBRARIES = { d3: d3Script, 'vega-lite': vegaScript }

export type Library = keyof typeof LIBRARIES

/** No network and nothing from ADA's origin: inline scripts and styles, the code from a
 * blob: URL, images and fonts only as data. */
export const FRAME_CSP =
  "default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob:; font-src data:"

// The frame is transparent like every widget, and the code's root fills it.
const BASE_CSS = `:root{color-scheme:light dark;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:14px;color:var(--ada-foreground)}
*{box-sizing:border-box}
html,body{height:100%;margin:0;overflow:hidden;background:transparent}
#root{position:relative;width:100%;height:100%;overflow:auto}`

export type CustomSpec = { code: string; css: string; libraries: Library[] }

/** The spec as the frame reads it; the backend has checked it. */
export function customSpec(spec: Record<string, unknown>): CustomSpec {
  const libraries = Array.isArray(spec.libraries) ? spec.libraries : []
  return {
    code: typeof spec.code === 'string' ? spec.code : '',
    css: typeof spec.css === 'string' ? spec.css : '',
    libraries: Object.keys(LIBRARIES).filter((name): name is Library => libraries.includes(name)),
  }
}

/** The document of the frame that runs the code: the CSP, the widget's CSS, the listed
 * libraries and the script that runs the code (child-main.ts), all inline. */
export function frameDocument({ css, libraries }: Pick<CustomSpec, 'css' | 'libraries'>): string {
  const scripts = [...libraries.map((name) => LIBRARIES[name]), childScript]
  return [
    '<!doctype html><html lang="en"><head><meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP}">`,
    `<style>${BASE_CSS}</style>`,
    // Kept inside its element: "</style" would end it.
    `<style>${css.replace(/<\/style/gi, '<\\/style')}</style>`,
    '</head><body><div id="root"></div>',
    ...scripts.map((script) => `<script>${script}</script>`),
    '</body></html>',
  ].join('')
}

function dataset(input: WidgetData): Dataset {
  return {
    columns: input.columns,
    rows: rowsAsValues({ data: input }),
    roles: input.output.roles ?? {},
    truncated: input.truncated,
  }
}

/** The data as the code reads it: every input's rows as objects keyed by column name. */
export function customData({ data, inputs }: Pick<Loaded, 'data' | 'inputs'>): Data {
  const all = Object.fromEntries(Object.entries(inputs ?? { main: data }).map(([name, input]) => [name, dataset(input)]))
  return {
    main: all.main ?? dataset(data),
    inputs: all,
    run_id: data.run_id,
    // Kept for code that reads it; see protocol.ts.
    is_scenario: data.is_scenario,
    is_stale: data.is_stale,
  }
}

/** The page's colours for the current theme, as styles.css defines them. */
export function readColors(root: Element = document.documentElement): Colors {
  const css = getComputedStyle(root)
  const color = (name: string) => css.getPropertyValue(name).trim()
  return {
    foreground: color('--text-primary'),
    muted: color('--text-muted'),
    background: color('--surface'),
    border: color('--grid'),
    accent: color('--accent'),
    positive: color('--positive'),
    negative: color('--negative'),
    warning: color('--warning'),
    series: Array.from({ length: 8 }, (_, i) => color(`--series-${i + 1}`)),
  }
}
