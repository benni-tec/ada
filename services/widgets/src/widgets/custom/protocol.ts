// A custom widget runs an agent's code in a sandboxed frame inside the widget's own frame.
// These are what the code gets (`render(root, data, ada)`) and the messages between the
// two frames: the widget's frame (custom.tsx, on ADA's origin) sends the code, the data,
// the theme and the size; the code's frame (child.ts: no network, no ADA origin) says
// whether it drew.

import type { DateGrain, NumberFormat } from '@/lib/columns'
import type { Column, Roles } from '@/lib/types'

/** One input of the widget: its rows as objects keyed by column name, dates as ISO strings. */
export type Dataset = {
  columns: Column[]
  rows: Record<string, unknown>[]
  roles: Roles
  /** The input had more rows than were read (5,000). */
  truncated: boolean
}

export type Data = {
  /** The widget's own operator. */
  main: Dataset
  /** Every input by name, "main" included. */
  inputs: Record<string, Dataset>
  run_id: string
  is_scenario: boolean
  is_stale: boolean
}

export type Theme = 'light' | 'dark'

export type Colors = {
  foreground: string
  muted: string
  background: string
  border: string
  accent: string
  positive: string
  negative: string
  warning: string
  /** Eight categorical colours, in order. */
  series: string[]
}

export type Size = { width: number; height: number }

/** vega-embed for the code, set up for the frame: the page's theme as its config, the
 * chart widget's interpreter and loader (libraries/vega.ts). */
export type VegaEmbedFor = (config: Record<string, unknown>, dark: boolean) => unknown

export type Ada = {
  theme: Theme
  colors: Colors
  size: Size
  onResize(callback: (size: Size) => void): void
  format: {
    number(value: number | null, options?: { format?: NumberFormat; decimals?: number }): string
    date(value: string | null, options?: { grain?: DateGrain }): string
  }
  /** Only the libraries the spec lists. */
  libraries: { d3?: unknown; vegaEmbed?: unknown }
  /** Reports a problem without throwing. */
  error(message: string): void
}

/** Draw (again): on the first message, a new run, or a theme change. `seq` tells this
 * drawing's answers from an earlier one's. */
export type Draw = {
  type: 'render'
  seq: number
  code: string
  data: Data
  theme: Theme
  colors: Colors
  size: Size
  /** The page's theme as a Vega config, for `ada.libraries.vegaEmbed`. */
  vegaConfig: Record<string, unknown>
}

/** From the widget's frame to the code's. */
export type HostMessage = Draw | { type: 'resize'; size: Size }

/** From the code's frame to the widget's. */
export type ChildMessage =
  | { type: 'ready' }
  | { type: 'rendered'; seq: number }
  | { type: 'error'; seq: number; message: string }
