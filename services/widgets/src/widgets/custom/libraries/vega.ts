// Vega-Lite for a custom widget whose spec lists "vega-lite": the chart widget's pinned
// vega, vega-lite and vega-embed, built into a script (`?script`) that leaves a vega-embed
// factory on the frame's global, where child-main.ts finds it.

import embed, { type EmbedOptions, type VisualizationSpec } from 'vega-embed'

import { sandboxed } from '@/widgets/chart/embed'

import type { VegaEmbedFor } from '../protocol'

/** vega-embed as the code calls it, with the page's theme as its config (the spec's own
 * config and the code's options still win) and, whatever the options say, the chart
 * widget's interpreter and loader: the frame's CSP has no `unsafe-eval`, and a view
 * loads nothing. */
const vegaEmbedFor: VegaEmbedFor =
  (config, dark) =>
  (element: HTMLElement | string, spec: VisualizationSpec | string, options: EmbedOptions = {}) =>
    embed(element, spec, {
      renderer: 'svg',
      actions: false,
      defaultStyle: false,
      tooltip: { theme: dark ? 'dark' : 'light' },
      ...options,
      // A config by address would be loaded: only an object is taken.
      config: { ...config, ...(typeof options.config === 'object' ? options.config : {}) },
      ...sandboxed,
    })

;(globalThis as typeof globalThis & { adaVegaEmbed?: VegaEmbedFor }).adaVegaEmbed = vegaEmbedFor
