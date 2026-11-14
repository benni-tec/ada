import type { AnyRouteMatch } from '@tanstack/react-router'
import type { ComponentType } from 'react'

declare module '@tanstack/react-router' {
  interface StaticDataRouteOption {
    /** The trail's steps after the project, for a page inside a project. */
    crumb?: ComponentType
    /** The page shows data frozen at a run, so "Live" would claim something untrue. */
    frozen?: boolean
  }
}

/** What the deepest matched route says about itself. */
export function pageOf(matches: AnyRouteMatch[]) {
  const leaf = matches.at(-1)
  return { Crumb: leaf?.staticData.crumb, frozen: leaf?.staticData.frozen ?? false }
}
