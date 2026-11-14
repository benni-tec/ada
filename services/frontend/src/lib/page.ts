import type { AnyRouteMatch } from '@tanstack/react-router'

declare module '@tanstack/react-router' {
  interface StaticDataRouteOption {
    /** The page shows data frozen at a run, so "Live" would claim something untrue. */
    frozen?: boolean
  }
}

/** What the deepest matched route says about itself. */
export function pageOf(matches: AnyRouteMatch[]) {
  const leaf = matches.at(-1)
  return { frozen: leaf?.staticData.frozen ?? false }
}
