import { useEffect, useMemo, useRef, useState } from 'react'

import { inMcpHost, openFromMcpHost, reportRender } from '@/lib/host'
import type { Loaded } from '@/lib/runtime'
import { useDark } from '@/lib/theme'
import { readPalette, vegaConfig } from '@/widgets/chart/spec'

import { customData, customSpec, frameDocument, readColors } from './frame'
import type { ChildMessage, HostMessage, Size } from './protocol'

/** In an MCP host the nested frame may not be allowed: without a word from it by then, the
 * widget points to ADA instead. */
const READY_MS = 3000
/** As much of an error as ADA keeps. */
const MAX_ERROR = 2000

type Outcome = { status: 'drawing' } | { status: 'drawn' } | { status: 'error'; message: string }

function measure(element: Element | null): Size {
  const box = element?.getBoundingClientRect()
  return { width: Math.round(box?.width ?? 0), height: Math.round(box?.height ?? 0) }
}

function OpenInAda({ url }: { url?: string }) {
  const text = 'Open in ADA to see this widget'
  if (!url) return <p className="ada-note">{text}</p>
  return (
    <p className="ada-note">
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        onClick={(event) => {
          // The host's frame may open nothing itself: the host opens it.
          event.preventDefault()
          openFromMcpHost(url).catch(() => window.open(url, '_blank', 'noreferrer'))
        }}
      >
        {text}
      </a>
    </p>
  )
}

/**
 * A widget drawn by an agent's code (spec: `code`, an ES module whose default export draws;
 * `css`; `libraries`: "d3", "vega-lite").
 *
 * The code runs in a frame inside this one, sandboxed without ADA's origin, whose CSP
 * allows no network. It gets the data of every input, the theme, the colours and the size
 * by postMessage, and draws again for new data or a theme change. What went wrong shows
 * here, and is reported to ADA when it differs from what ADA has (not in an MCP host).
 */
export function Custom({ widget, data, inputs, url }: Loaded) {
  const frame = useRef<HTMLIFrameElement>(null)
  const dark = useDark()
  const hosted = inMcpHost()
  const spec = useMemo(() => customSpec(widget.spec), [widget.spec])
  const srcDoc = useMemo(() => frameDocument(spec), [spec])
  // How often the code's frame said it is ready: once per document it loads.
  const [readies, setReadies] = useState(0)
  const [late, setLate] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>({ status: 'drawing' })
  const seq = useRef(0)
  const reported = useRef(widget.render_error ?? null)

  const draw = useMemo(
    () => ({
      code: spec.code,
      data: customData({ data, inputs }),
      theme: dark ? ('dark' as const) : ('light' as const),
      colors: readColors(),
      vegaConfig: vegaConfig(readPalette()),
    }),
    [spec, data, inputs, dark],
  )

  // Only the frame made here speaks for the code, and only about the latest drawing.
  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return
      const message = event.data as ChildMessage
      if (message?.type === 'ready') setReadies((count) => count + 1)
      else if (message?.type === 'rendered' && message.seq === seq.current) setOutcome({ status: 'drawn' })
      else if (message?.type === 'error' && message.seq === seq.current) {
        setOutcome({ status: 'error', message: String(message.message) })
      }
    }
    window.addEventListener('message', listen)
    return () => window.removeEventListener('message', listen)
  }, [])

  // What was shown stays until the new drawing answers.
  useEffect(() => {
    if (readies === 0) return
    seq.current += 1
    const message: HostMessage = { type: 'render', seq: seq.current, ...draw, size: measure(frame.current) }
    frame.current?.contentWindow?.postMessage(message, '*')
  }, [readies, draw])

  // Resizing does not draw again: the code follows it with ada.onResize.
  useEffect(() => {
    const element = frame.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      const message: HostMessage = { type: 'resize', size: measure(element) }
      element.contentWindow?.postMessage(message, '*')
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!hosted || readies > 0) return
    const timer = setTimeout(() => setLate(true), READY_MS)
    return () => clearTimeout(timer)
  }, [hosted, readies])

  useEffect(() => {
    if (hosted || outcome.status === 'drawing') return
    const error = outcome.status === 'error' ? outcome.message.slice(0, MAX_ERROR) : null
    if (error === reported.current) return
    reported.current = error
    void reportRender(widget.id, error)
  }, [hosted, outcome, widget.id])

  const waiting = late && readies === 0
  return (
    <>
      {outcome.status === 'error' && (
        <p role="alert" className="ada-error">
          This widget could not be drawn: {outcome.message}
        </p>
      )}
      {hosted && (waiting || outcome.status === 'error') && <OpenInAda url={url} />}
      <iframe
        ref={frame}
        className="ada-custom"
        title={widget.title || 'Custom widget'}
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        hidden={waiting}
      />
    </>
  )
}
