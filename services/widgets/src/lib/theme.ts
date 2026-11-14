// The theme a widget is drawn in: the page's, as followTheme (host.ts) sets it on the root,
// else the system's.

import { useSyncExternalStore } from 'react'

const DARK = '(prefers-color-scheme: dark)'

export function isDark(): boolean {
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

/** True while the widget is drawn dark; re-renders when that changes. */
export function useDark(): boolean {
  return useSyncExternalStore(subscribeTheme, isDark)
}
