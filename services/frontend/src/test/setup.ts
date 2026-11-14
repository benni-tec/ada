import '@testing-library/jest-dom/vitest'

import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Whole routes render with many requests each; on a busy machine one second is too short.
configure({ asyncUtilTimeout: 5000 })

// The router scrolls to the top on navigation; jsdom does not implement scrolling.
window.scrollTo = () => {}
Element.prototype.scrollIntoView ??= () => {}
Element.prototype.scrollTo ??= () => {}

// What jsdom lacks and the shadcn components (Radix, cmdk, the sidebar) use: media queries
// (a wide screen, light mode), element observers and pointer capture.
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.setPointerCapture ??= () => {}
Element.prototype.releasePointerCapture ??= () => {}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})
