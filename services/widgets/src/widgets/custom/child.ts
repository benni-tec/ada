// Runs a custom widget's code, in the sandboxed frame inside the widget (child-main.ts
// starts it there). It knows only what the widget's frame sends, and says back only
// whether the code drew.

import { formatAs, formatDate, isNumberFormat, toNumber } from '@/lib/columns'

import type { Ada, ChildMessage, Draw, HostMessage, Size, VegaEmbedFor } from './protocol'

export type ChildIo = {
  send(message: ChildMessage): void
  /** Messages from the widget's frame, its source already checked. */
  listen(handler: (message: HostMessage) => void): void
  /** Where errors outside `render` arrive: `error` and `unhandledrejection` events. */
  errors: EventTarget
  root: HTMLElement
  /** The code as an ES module. */
  load(code: string): Promise<{ default?: unknown }>
  /** The libraries the spec lists, as the frame's scripts left them. */
  libraries: { d3?: unknown; vegaEmbed?: VegaEmbedFor }
}

type Render = (root: HTMLElement, data: Draw['data'], ada: Ada) => unknown

/** An error as the agent that wrote the code can fix it: its message, and its line in the
 * code when the stack names one (the code runs from a blob: URL). */
export function describe(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    const message = String(error.message)
    const stack = 'stack' in error ? String(error.stack) : ''
    const line = /blob:[^\s)]*:(\d+):\d+/.exec(stack)?.[1]
    return line ? `${message} (line ${line})` : message
  }
  return String(error)
}

function themeDocument(root: HTMLElement, { theme, colors }: Draw) {
  const element = root.ownerDocument.documentElement
  element.dataset.theme = theme
  element.style.colorScheme = theme
  // The colours as CSS variables too, for the widget's css: --ada-foreground, --ada-series-1.
  const { series, ...named } = colors
  for (const [name, value] of Object.entries(named)) element.style.setProperty(`--ada-${name}`, value)
  series.forEach((value, i) => element.style.setProperty(`--ada-series-${i + 1}`, value))
}

export function startChild(io: ChildIo): void {
  let current: Draw | null = null
  let failed: number | null = null
  let cleanup: (() => void) | null = null
  let module: { code: string; render: Promise<Render> } | null = null
  let ada: Ada | null = null
  let listeners: ((size: Size) => void)[] = []

  const fail = (seq: number, error: unknown) => {
    if (seq !== current?.seq) return
    failed = seq
    io.send({ type: 'error', seq, message: describe(error) })
  }

  const renderOf = (code: string): Promise<Render> => {
    if (module?.code !== code) {
      const render = io.load(code).then((loaded) => {
        if (typeof loaded.default !== 'function') {
          throw new Error('The code has no default export to call: export default function render(root, data, ada) {…}')
        }
        return loaded.default as Render
      })
      module = { code, render }
    }
    return module.render
  }

  const draw = async (message: Draw) => {
    current = message
    failed = null
    listeners = []
    try {
      cleanup?.()
    } catch (error) {
      fail(message.seq, error)
    }
    cleanup = null
    io.root.replaceChildren()
    themeDocument(io.root, message)
    const libraries = io.libraries
    ada = {
      theme: message.theme,
      colors: message.colors,
      size: message.size,
      onResize: (callback) => {
        if (current === message) listeners.push(callback)
      },
      format: {
        number: (value, options = {}) => {
          const number = toNumber(value)
          if (number === null) return '–'
          return formatAs(number, isNumberFormat(options.format) ? options.format : undefined, options.decimals)
        },
        date: (value, options = {}) => formatDate(value, options.grain),
      },
      libraries: {
        ...(libraries.d3 !== undefined && { d3: libraries.d3 }),
        ...(libraries.vegaEmbed && { vegaEmbed: libraries.vegaEmbed(message.vegaConfig, message.theme === 'dark') }),
      },
      error: (text) => fail(message.seq, text),
    }
    try {
      const render = await renderOf(message.code)
      if (current !== message) return
      const result = await render(io.root, message.data, ada)
      // A newer drawing started meanwhile: this one's cleanup is due at once.
      if (current !== message) {
        if (typeof result === 'function') result()
        return
      }
      cleanup = typeof result === 'function' ? (result as () => void) : null
      if (failed !== message.seq) io.send({ type: 'rendered', seq: message.seq })
    } catch (error) {
      fail(message.seq, error)
    }
  }

  const resize = (size: Size) => {
    if (ada) ada.size = size
    for (const listener of listeners) {
      try {
        listener(size)
      } catch (error) {
        if (current) fail(current.seq, error)
      }
    }
  }

  io.errors.addEventListener('error', (event) => {
    const { error, message } = event as ErrorEvent
    // Not an error: the browser deferred a resize notification (a view that fits its container).
    if (!error && /^ResizeObserver loop/.test(message)) return
    if (current) fail(current.seq, error ?? message)
  })
  io.errors.addEventListener('unhandledrejection', (event) => {
    if (current) fail(current.seq, (event as PromiseRejectionEvent).reason)
  })
  io.listen((message) => {
    if (message.type === 'render') void draw(message)
    else if (message.type === 'resize') resize(message.size)
  })
  io.send({ type: 'ready' })
}
