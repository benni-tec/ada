import { useState } from 'react'

/** The attachments' share of the session page's width, in percent, and its bounds. */
export const paneWidth = { initial: 50, min: 25, max: 75, step: 5 }

const storageKey = 'ada-attachments-width'

const clampWidth = (value: number) => Math.min(paneWidth.max, Math.max(paneWidth.min, value))

/** The width last chosen in this browser. Storage may be refused or hold something else:
 * the halves are even then. */
function rememberedWidth(): number {
  try {
    const value = Number(localStorage.getItem(storageKey))
    return Number.isFinite(value) && value > 0 ? clampWidth(value) : paneWidth.initial
  } catch {
    return paneWidth.initial
  }
}

function rememberWidth(value: number) {
  try {
    localStorage.setItem(storageKey, String(value))
  } catch {
    // Not remembered; the page works without it.
  }
}

/** The attachments' width, remembered per browser once the person has set it. */
export function usePaneWidth() {
  const [width, setWidth] = useState(rememberedWidth)
  const set = (value: number, remember: boolean) => {
    const next = Math.round(clampWidth(value) * 10) / 10
    setWidth(next)
    if (remember) rememberWidth(next)
  }
  return [width, set] as const
}
