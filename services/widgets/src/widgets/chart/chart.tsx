import { useEffect, useMemo, useRef, useState } from 'react'
import { Error as LOG_ERROR } from 'vega'
import embed, { type Result, type VisualizationSpec } from 'vega-embed'

import type { Loaded } from '@/lib/runtime'
import { useDark } from '@/lib/theme'

import { sandboxed } from './embed'
import { chartSpec, readPalette, sizesItself, vegaConfig } from './spec'

/**
 * A Vega-Lite chart of the operator's output.
 *
 * Spec: a Vega-Lite spec without data (a `mark`, `layer`, `concat`, `facet` or `repeat`);
 * the rows are put in as `data: {values}`. Expressions run in Vega's interpreter, so the
 * frame needs no `unsafe-eval`. Follows the page's theme and the frame's size.
 */
export function Chart({ widget, data, roles }: Loaded) {
  const ref = useRef<HTMLDivElement>(null)
  const dark = useDark()
  const [problem, setProblem] = useState<string | null>(null)
  // The spec drawn last: until the current one is, the chart is busy (and a frame sized to
  // its content waits for it).
  const [drawn, setDrawn] = useState<unknown>(null)
  const spec = useMemo(() => chartSpec({ widget, data, roles }), [widget, data, roles])

  useEffect(() => {
    const element = ref.current
    if (!element) return
    let current = true
    let result: Result | undefined
    setProblem(null)
    embed(element, spec as VisualizationSpec, {
      mode: 'vega-lite',
      renderer: 'svg',
      actions: false,
      defaultStyle: false,
      ...sandboxed,
      logLevel: LOG_ERROR,
      config: vegaConfig(readPalette()),
      tooltip: { theme: dark ? 'dark' : 'light' },
    }).then(
      (embedded) => {
        if (current) {
          result = embedded
          setDrawn(spec)
        } else {
          embedded.finalize()
        }
      },
      (error: unknown) => {
        if (!current) return
        setProblem(error instanceof Error ? error.message : String(error))
        setDrawn(spec)
      },
    )
    return () => {
      current = false
      result?.finalize()
    }
  }, [spec, dark])

  const title = widget.title || 'Chart'
  return (
    <>
      {problem && (
        <p role="alert" className="ada-error">
          This chart’s spec does not render: {problem}
        </p>
      )}
      {/* Sized by its spec, it keeps its own height where the page fits frames to content. */}
      <div className={sizesItself(widget.spec) ? 'ada-chart ada-chart-intrinsic' : 'ada-chart'} role="figure" aria-label={title} aria-busy={drawn !== spec}>
        <div className="ada-vega" ref={ref} />
      </div>
    </>
  )
}
