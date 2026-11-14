// What every Vega view in a widget runs with: the chart widget's, and a custom widget's
// `ada.libraries.vegaEmbed`.

import { loader, type Loader } from 'vega'
import type { EmbedOptions } from 'vega-embed'
import { expressionInterpreter } from 'vega-interpreter'

// A view's only data is what the widget puts in. The backend refuses `url` and `data` in a
// chart's spec; this loader refuses any file or image a spec could still ask for.
const refuse = () => Promise.reject(new Error('A chart loads nothing: its data is its operator’s output'))
const noFiles: Loader = { ...loader(), load: refuse, sanitize: refuse, http: refuse, file: refuse }

/** Expressions run in Vega's interpreter, so no code is generated from strings and a frame
 * CSP needs no `unsafe-eval`; and nothing is loaded. */
export const sandboxed = { ast: true, expr: expressionInterpreter, loader: noFiles } satisfies EmbedOptions
