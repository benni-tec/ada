import { createContext, useContext } from 'react'

export type Theme = 'light' | 'dark' | 'system'

type ThemeState = { theme: Theme; resolved: 'light' | 'dark'; setTheme: (theme: Theme) => void }

/** The theme picked and the one in use (ThemeProvider in theme.tsx). */
export const ThemeContext = createContext<ThemeState>({ theme: 'system', resolved: 'light', setTheme: () => {} })

export function useTheme() {
  return useContext(ThemeContext)
}
