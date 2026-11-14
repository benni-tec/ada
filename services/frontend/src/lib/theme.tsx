import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'

import { ThemeContext, type Theme } from './theme-context'

const storageKey = 'ada-theme'
const darkQuery = '(prefers-color-scheme: dark)'

function stored(): Theme {
  try {
    const value = localStorage.getItem(storageKey)
    return value === 'light' || value === 'dark' ? value : 'system'
  } catch {
    // Storage can be blocked; the system's choice is a fine default.
    return 'system'
  }
}

function subscribeToSystem(onChange: () => void) {
  const query = window.matchMedia(darkQuery)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/**
 * Light or dark, following the system unless the person picked one. shadcn's colours
 * switch on a `.dark` class on <html>, so the class is set here. `color-scheme` goes with
 * it (index.css): widget frames inherit it, and a frame's `prefers-color-scheme` follows
 * its element's scheme, so the widgets switch with the page instead of with the system.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(stored)
  const systemDark = useSyncExternalStore(
    subscribeToSystem,
    () => window.matchMedia(darkQuery).matches,
    () => false,
  )
  const resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    try {
      if (next === 'system') localStorage.removeItem(storageKey)
      else localStorage.setItem(storageKey, next)
    } catch {
      // Not remembered, but applied.
    }
  }, [])

  return <ThemeContext value={{ theme, resolved, setTheme }}>{children}</ThemeContext>
}
