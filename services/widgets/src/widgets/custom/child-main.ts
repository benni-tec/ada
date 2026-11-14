// The script of the sandboxed frame that runs a custom widget's code, built into a string
// (`?script`) that frame.ts writes into the frame's document. Only the frame around it is
// listened to; the code is imported from a blob: URL, the one source besides inline
// scripts that the frame's CSP allows.

import { startChild } from './child'
import type { VegaEmbedFor } from './protocol'

// What the library scripts before this one left (libraries/*.ts), when the spec lists them.
const listed = globalThis as typeof globalThis & { d3?: unknown; adaVegaEmbed?: VegaEmbedFor }

startChild({
  send: (message) => window.parent.postMessage(message, '*'),
  listen: (handler) =>
    window.addEventListener('message', (event) => {
      if (event.source === window.parent) handler(event.data)
    }),
  errors: window,
  root: document.getElementById('root')!,
  load: async (code) => {
    const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }))
    try {
      return await import(/* @vite-ignore */ url)
    } finally {
      URL.revokeObjectURL(url)
    }
  },
  libraries: { d3: listed.d3, vegaEmbed: listed.adaVegaEmbed },
})
