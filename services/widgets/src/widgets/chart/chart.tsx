import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Error as LOG_ERROR, loader, type Loader } from 'vega'
import embed, { type Result, type VisualizationSpec } from 'vega-embed'
import { expressionInterpreter } from 'vega-interpreter'

import type { Loaded } from '@/lib/runtime'

import { chartSpec, readPalette, sizesItself, vegaConfig } from './spec'

// A chart's only data is its operator's rows. The backend refuses `url` and `data` in a
// spec; this loader refuses any file or image a spec could still ask for.
const refuse = () => Promise.reject(new Error('A chart loads nothing: its data is its operator’s output'))
const noFiles: Loader = { ...loader(), load: refuse, sanitize: refuse, http: refuse, file: refuse }

const DARK = '(prefers-color-scheme: dark)'

function isDark(): boolean {
  const theme = document.documentElement.dataset.theme
  if (theme === 'dark' || theme === 'light') return theme === 'dark'
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK).matches
}

/** Follows the theme as followTheme sets it on the root, and the system's. */
function subscribeTheme(listener: () => void): () => void {
  const observer = new MutationObserver(listener)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  const media = typeof window.matchMedia === 'function' ? window.matchMedia(DARK) : null
  media?.addEventListener('change', listener)
  return () => {
    observer.disconnect()
    media?.removeEventListener('change', listener)
  }
}

/**
 * A Vega-Lite chart of the operator's output.
 *
 * Spec: a Vega-Lite spec without data (a `mark`, `layer`, `concat`, `facet` or `repeat`);
 * the rows are put in as `data: {values}`. Expressions run in Vega's interpreter, so the
 * frame needs no `unsafe-eval`. Follows the page's theme and the frame's size.
 */
export function Chart({ widget, data, roles }: Loaded) {
  const ref = useRef<HTMLDivElement>(null)
  const dark = useSyncExternalStore(subscribeTheme, isDark)
  const [problem, setProblem] = useState<string | null>(null)
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
      ast: true,
      expr: expressionInterpreter,
      loader: noFiles,
      logLevel: LOG_ERROR,
      config: vegaConfig(readPalette()),
      tooltip: { theme: dark ? 'dark' : 'light' },
    }).then(
      (embedded) => {
        if (current) result = embedded
        else embedded.finalize()
      },
      (error: unknown) => current && setProblem(error instanceof Error ? error.message : String(error)),
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
      <div className={sizesItself(widget.spec) ? 'ada-chart ada-chart-intrinsic' : 'ada-chart'} role="figure" aria-label={title}>
        <div className="ada-vega" ref={ref} />
      </div>
    </>
  )
}
