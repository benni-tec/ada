import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom has no canvas and says so on every use; Vega (the chart widget) then estimates
// text widths, which is all a test needs.
HTMLCanvasElement.prototype.getContext = () => null

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.location.hash = ''
})
